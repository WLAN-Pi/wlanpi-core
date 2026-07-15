# P0: Core worker API and UI platform foundations

**Status:** Active — implementation starting  
**Version:** 2026.06.6  
**Related:** [UI platform architecture](/home/wlanpi/docs/UI-plan.md), [API integration guide](./API-INTEGRATION-GUIDE.md), [deprecated endpoints](./API-DEPRECATED-ENDPOINTS.md), [gap matrix](./p0-api-gap-matrix.csv), [API test matrix](./P0-api-test-matrix.md), [datetime API guide](./P0-system-datetime-api.md), [reg-domain API guide](./P0-system-reg-domain-api.md), [WLAN scan API guide](./P0-utils-wlan-scan-api.md), [WLAN drivers API guide](./P0-network-wlan-drivers-api.md), [reachability & speedtest guide](./P0-utils-reachability-speedtest-api.md), [Wi-Fi capture API design](./P0-wifi-capture-api.md), [Wi-Fi capture consumer guide](./P0-wifi-capture-consumer-guide.md), [NETWORK_CONFIG.md](../NETWORK_CONFIG.md)

---

## 1. Purpose

P0 delivers the minimum **core worker primitives** and documents the **wlanpi-ui helper layer** needed so every UI surface (panel, TUI, mobile, WebUI) can drive the same capabilities — without duplicating shell scripts or exposing raw namespace internals.

**Spreadsheet:** [`docs/p0-api-gap-matrix.csv`](./p0-api-gap-matrix.csv) — verified against `wlanpi-core` on branch `dev` (OpenAPI at `/docs`).

### P0 counts (from gap matrix)

| Status | Core endpoints | Action |
|--------|----------------|--------|
| **Live** | 28 | Bind in wlanpi-ui capability registry |
| **Gap — build in core** | 38 | Implement in `wlanpi-core` |
| **Gap — UI→Core job** | 6 | Core worker + wlanpi-ui job runner |
| **wlanpi-ui only** | 8 | Session, menu, adapter helper, config helper |

---

## 2. Agreed policy decisions

### 2.1 Authentication — low burden for logged-in users

| Caller | Mechanism | User experience |
|--------|-----------|-----------------|
| Remote clients (mobile, WebUI) | **JWT** via `POST /api/v1/auth/token` | Login once; store Bearer token; attach to every request until expiry (default 7 days) or revoke |
| wlanpi-ui → wlanpi-core (localhost) | **HMAC** (`X-Request-Signature`) | Transparent to end user; wlanpi-ui holds shared secret |
| Panel GPIO / local automation | HMAC or pre-provisioned service identity | No per-button auth |

**Principle:** An authenticated user must not re-authenticate for routine operations. JWT on the UI platform boundary is sufficient for remote clients. Core validates the token on each request but that is invisible to the user.

Capture WebSocket (`/streaming/capture`) currently has **no auth** — add HMAC or JWT before UI platform exposes capture jobs in P0.

### 2.2 Device mode vs API availability

Two different concepts must not be conflated:

| Concept | Behaviour |
|---------|-----------|
| **Device mode** (`/etc/wlanpi-state`: classic, hotspot, wiperf, etc.) | Read via `GET /system/device/info` → `mode` |
| **Namespace config activate/deactivate** | **Classic mode only** — enforced at startup and in `NetworkNamespaceService` init. Non-classic modes skip namespace auto-restore. |
| **All other core APIs** | **Must work in any device mode** — queries, service control, timezone, reg-domain, scan (where adapters exist), etc. |

### 2.3 Mode switch and reboot

| Operation | Policy |
|-----------|--------|
| **Reboot** (`POST /system/reboot`) | Auth-gated. Namespace persistence on reboot is already handled: active config id written to `current.txt`, restored on core startup **in classic mode only**. |
| **Shutdown** (`POST /system/shutdown`) | Auth-gated. |
| **Mode switch** (`POST /system/mode/switch`) | Auth-gated. Must work from any current mode. **If a namespace config is active**, core returns `409 Conflict` with a clear message unless `force: true` (which deactivates configs first). UI must confirm with user. |

Mode switch wraps existing switcher scripts (`wlanpi_core/constants.py`: `HOTSPOT_SWITCHER_FILE`, etc.).

### 2.4 Namespace-aware Wi-Fi scan — hide complexity from end users

End users should not need to understand network namespaces. Core scan primitive:

```
GET /api/v1/utils/wlan/scan
```

**Query parameters:**

| Param | Required | Description |
|-------|----------|-------------|
| `iface` | No | Interface to scan from (display name, e.g. `wlanpi0`) |
| `namespace` | No | Namespace name, or omit for root |
| `hidden` | No | Include hidden SSIDs (default `true`) |

**Adapter selection algorithm** (when `iface` not provided):

1. Call internal adapter enumeration (same data as `GET /network/config/status`).
2. Collect interfaces where `type == monitor` (or `mode == monitor` from iw output).
3. **0 monitor adapters** → scan from first suitable **managed** adapter in root, or return `422` with `{ "error": "NO_SCAN_ADAPTER", "candidates": [] }`.
4. **1 monitor adapter** → auto-select; include `selectedAdapter` in response metadata.
5. **2+ monitor adapters** → do **not** scan; return `200` with `{ "needsSelection": true, "candidates": [ { "iface", "namespace", "label" } ] }`. UI asks user, retries with `iface` + `namespace`.

**Response metadata** (all successful scans):

```json
{
  "selectedAdapter": { "iface": "wlanpi0", "namespace": "root", "label": "wlanpi0 (monitor)" },
  "networks": [ { "ssid": "...", "bssid": "...", "signal": -65, "freq": 2412 } ],
  "scannedAt": "2026-06-06T12:00:00Z"
}
```

**UI platform:** wraps as job with `freshnessSec: 30`. Job WS streams BSS lines for TUI/panel; session WS stays small. See [WLAN scan integration guide](./P0-utils-wlan-scan-api.md).

#### 2.4.1 Scan architecture — snapshot vs continuous

Core deliberately separates **single-shot scan** from **continuous RF observation**:

| Primitive | Mechanism | Use when |
|-----------|-----------|----------|
| **`GET /utils/wlan/scan`** | One `wpa_cli scan` + parse `scan_results` via `wlanpi_core/wpa/scan.py` | REST, MCP, 3rd-party HTTP, UI job polling (`freshnessSec`) |
| **`/streaming/capture` WebSocket** | Passive `dumpcap` byte stream + channel hop | Live survey, scanner tools, future BSS extraction from beacons |

**Why not loop `wpa_cli scan` on a WebSocket?** Active scan is driver-limited, can disrupt association, and does not match how scanner tools work. Continuous “scanning” is passive beacon capture (monitor mode + pcap), not repeated WPA supplicant scans.

**Code layering (for maintainers):**

```
wpa/scan.py      → shared wpa_cli scan primitives (parse, fetch, run_interface_scan)
wlan/scan.py     → adapter selection + API response shape
wpa/status.py    → connection status; reuses scan parser for connected BSSID signal
connection/      → polls get_wpa_status only; not AP discovery
namespaces/      → no scan; netns lifecycle only
```

**UI integration surfaces:**

1. **Standard REST** — call `GET /utils/wlan/scan` directly.
2. **Periodic display** — wlanpi-ui job runner polls REST; push deltas on job WebSocket (core stays stateless).
3. **MCP / AI tools** — same REST + OpenAPI schema; no core WebSocket required.
4. **3rd-party tools** — stable JSON `networks[]`; legacy `GET /network/wlan/scan` will delegate here then deprecate.

Future continuous BSS events belong on a **capture-derived** path (beacon parser over `/streaming/capture`), not an extension of `run_interface_scan()`.

**On-device active scan (iwlwifi / WLAN Pi classic):** monitor VIF (`wlanpi0`) often cannot `iw scan` (-95). Core delegates to managed sibling (`wlan0`), brings the link up, and uses `iw dev wlan0 scan` when `wpa_supplicant` is absent. `selectedAdapter` reports the interface that actually scanned.

### 2.5 NetConfig and namespace management — wlanpi-ui helper layer

The **web-app** already builds `NetConfig` JSON and calls core `/network/config/*` directly. **TUI, panel, and mobile** need a friendlier layer — not raw schema, but functional state:

> "wlanpi0 is in monitor mode, channel 36"  
> "wlan1 is in managed mode, connected to SSID **MyNetwork** (provisioned)"  
> "Config **field** is active"

This belongs in **wlanpi-ui**, not core. Core keeps structured primitives; wlanpi-ui translates.

#### wlanpi-ui endpoints (P0)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/ui/adapters/summary` | Human-readable adapter list |
| GET | `/ui/network/configs` | Config list with display names and active state |
| POST | `/ui/network/config/save` | Simplified save: `{ id, adapters: [{ iface, mode, ssid?, psk?, namespace? }] }` → builds `NetConfig` JSON, calls core |
| POST | `/ui/network/config/activate` | Wrapper: `{ id, confirm?: true }` → core activate |
| POST | `/ui/network/config/deactivate` | Wrapper → core deactivate |

#### Adapter summary — composition (no new core API required for P0)

wlanpi-ui `GET /ui/adapters/summary` calls:

1. `GET /api/v1/network/config/status` — per-namespace `iw dev` (type, channel, ssid)
2. `GET /api/v1/network/config/` — which config id is active
3. `GET /api/v1/network/config/{active_id}` — config structure (credentials redacted by core)

**Translation rules:**

| iw `type` | ssid present | wpa_state unknown | Display string |
|-----------|--------------|-------------------|----------------|
| `monitor` | — | — | `{iface} — monitor mode, {channel}` |
| `managed` | yes | — | `{iface} — connected to **{ssid}**, {channel}` |
| `managed` | no | — | `{iface} — managed mode, not associated` |
| any | — | namespace != root | Prefix with namespace label only if multiple namespaces have adapters |

**Provisioned vs connected:** After activate, core returns `status: "provisioned"`. wlanpi-ui polls `config/status` every 2s (or job WS) until `ssid` appears in iw output or timeout. Display transitions: `Connecting…` → `Connected to **{ssid}**`.

P1 adds `GET /network/adapters/{iface}/connection` in core for precise `wpa_state` if iw-only detection is insufficient.

### 2.6 DBus — what is legacy and what stays

**Confirmed:** The P0 plan supersedes **wpa_supplicant DBus** (`fi.w1.wpa_supplicant1`) for all Wi-Fi operations. That stack in `network_service.py` is **legacy** — root-namespace only, no namespace awareness, polling-based, and parallel to the namespace/wpa_cli path the project is standardising on.

**Not superseded:** **systemd DBus** (`org.freedesktop.systemd1`) in `system_service.py` remains the implementation for service start/stop/status (and P0 `restart`). That is a different bus, different purpose, and stays unless we explicitly choose a `systemctl` subprocess refactor later.

| DBus stack | Status under P0 | Rationale |
|------------|-----------------|-----------|
| `fi.w1.wpa_supplicant1` (scan, connect, getConnected, getInterfaces) | **Legacy — deprecate** | Replaced by namespace config + `wpa_cli` + `iw` |
| `org.freedesktop.systemd1` (service control) | **Keep** | Allowed-service gate + live today; not Wi-Fi-related |
| Bluetooth | **No DBus in core** | `bluetooth_service` uses CLI/hardware paths |

#### Legacy endpoints — deprecate and repurpose paths

These routes keep their URLs through P0 for backward compatibility but must **not** receive new features. Implementations re-point to the namespace stack; OpenAPI marks them deprecated.

| Legacy endpoint | Current impl | P0 replacement | Repurpose plan |
|-----------------|--------------|----------------|----------------|
| `GET /network/wlan/scan` | wpa_supplicant DBus scan | `GET /utils/wlan/scan` | Thin wrapper → new impl, then remove DBus |
| `POST /network/wlan/set-dbus` | DBus AddNetwork | `POST /network/config/` + `POST /network/config/activate/{id}` | Deprecate; remove in P1 |
| `POST /network/wlan/set` | Broken namespace stub (`testns`) | Same as above | Deprecate; remove in P1 |
| `GET /network/wlan/getConnected` | DBus CurrentNetwork/BSS | `GET /network/config/status` + P1 `/network/adapters/{iface}/connection` | Reimplement via `wpa_cli status` |
| `GET /network/wlan/getInterfaces` | DBus interface list | `GET /network/config/status` or `adapters/discovery` | Reimplement via `iw dev` |
| `POST /network/wlan/revert` | Namespace service (valid) | `POST /network/config/deactivate/{id}` | Keep logic; align with config deactivate |

**New implementation stack** (already in core, P0 extends):

```
API endpoint
  → network_namespace_service / network_config utils  (connect, activate, deactivate)
  → wpa/supplicant.py, wpa/status.py, wpa/config.py   (wpa_cli, config files)
  → adapters/discovery.py, adapters/phy.py            (iw dev, phy listing)
  → namespaces/*, connection/monitor.py               (namespace ops, async connect)
```

**`network_service.py`:** Wi-Fi DBus code becomes dead after migration. Remove in P1 once consumers are off legacy paths. **Do not** build new P0 features on `AsyncDBusManager` or `setup_DBus_Supplicant_Access`.

**Consumer migration:** wlanpi-ui capability bindings and mobile app must target new paths only. Legacy paths exist solely for transitional compatibility.

---

## 3. Architecture reminder

```
Clients → wlanpi-ui (session WS, jobs, menu, adapter helper)
              ↓ JWT (remote) / HMAC (localhost)
         wlanpi-core (worker REST only)
```

Core does **not** implement: menu JSON, `UiSession`, job freshness cache, adapter display strings.

---

## 4. P0 core implementation workstreams

### Stream A — System primitives (priority 1)

| Endpoint | Wraps / notes |
|----------|---------------|
| `GET /system/battery` | Platform-specific read |
| `GET /system/datetime` | `date` / timedatectl |
| `GET /system/timezone` | `wlanpi-timezone` or `/etc/timezone` |
| `GET /system/timezone/list` | `timedatectl list-timezones` or script |
| `POST /system/timezone/set` | `wlanpi-timezone` |
| `POST /system/timezone/auto` | timedatectl NTP |
| `GET /system/reg-domain` | `wlanpi-reg-domain` |
| `GET /system/reg-domain/list` | Fixed FPMS country set |
| `POST /system/reg-domain/set` | `wlanpi-reg-domain` |
| `POST /system/reboot` | `systemctl reboot` / `shutdown -r` |
| `POST /system/shutdown` | `systemctl poweroff` |
| `POST /system/mode/switch` | Mode switcher scripts; 409 if config active |
| `GET /system/clients` | Hotspot lease/count script |
| `GET /system/ssid-passphrase` | Hostapd/profiler cred read |
| `POST /system/service/restart` | Extend existing systemd service module |

### Stream B — Network primitives (priority 2)

| Endpoint | Notes |
|----------|-------|
| `GET /network/info/publicip6` | `publicip6.sh` already in constants |
| `GET /network/routing` | Parse `ip route` |
| `GET /network/connections/tcp` | `ss -tn` or `/proc/net/tcp` |
| `GET /network/connections/udp` | `ss -un` |
| `POST /network/interfaces/{iface}/renew` | `networkctl renew`; 409 unless the root interface is managed by systemd-networkd |
| `GET /network/dhcp/leases` | Parse lease file |
| `GET /network/interfaces/{iface}/link-stats` | `ethtool` |
| `GET /network/wlan/usb-drivers` | `lsusb` + driver binding |
| `GET /network/wlan/pci-drivers` | `lspci` wireless |

### Stream C — Wi-Fi and utils workers (priority 3)

| Endpoint | Notes |
|----------|-------|
| `GET /utils/wlan/scan` | Namespace-aware; adapter selection algorithm §2.4 |
| `GET /wifi/capabilities` | `iw phy` dump per adapter |
| `GET /wifi/regulatory` | `iw reg get` |
| `GET /wifi/client/stations` | AP mode station list |
| `GET /wifi/client/link` | Client link stats |
| `GET /utils/speedtest` | Wrap LibreSpeed CLI; long-running |
| `GET /utils/cloud-test/{vendor}` | Per-vendor script |
| `POST /utils/blinker/start\|stop` | Restore commented utils_api code |
| `GET /utils/blinker/status` | |
| `POST /utils/freeradius/test` | |
| `POST /bluetooth/pair` | |

### Stream D — Capture REST bridge (priority 4)

**Design:** [P0-wifi-capture-api.md](./P0-wifi-capture-api.md) (core) · [P0-wifi-capture-consumer-guide.md](./P0-wifi-capture-consumer-guide.md) (app developers)

Session-based capture wrapping `streaming/connection_manager.py`:

| Endpoint | Purpose |
|----------|---------|
| `GET /wifi/capture/sources` | Namespace-aware discovery; usable/risk flags |
| `POST /wifi/capture/sessions` | Create session (`summary` default for MCP) |
| `GET /wifi/capture/sessions/{id}` | Status |
| `PATCH /wifi/capture/sessions/{id}` | Channels, filter (control token) |
| `POST /wifi/capture/sessions/{id}/stop` | Stop |
| `GET /wifi/capture/sessions/{id}/frames` | Parsed frames (MCP / summary mode) |
| `GET /wifi/capture/sessions/{id}/files` | Output file list |
| `WS /streaming/capture?session=&token=` | pcapng stream (subscribers) |

Secure by default: subscribers require token; `subscriberAccess: public` is explicit opt-in. Add auth to legacy WebSocket during migration.

---

## 5. P0 wlanpi-ui work (separate repo / fpms2 evolution)

| Deliverable | Depends on |
|-------------|------------|
| Serve menu + capabilities JSON | Asset package |
| `UiSession` + session WS | — |
| Job runner + `freshnessSec` | Core workers for scan/speedtest/cloud |
| Capability bindings for **Live** core endpoints | Gap matrix `bind` rows |
| `GET /ui/adapters/summary` | Core `config/status` (live today) |
| Config save/activate helpers | Core `config/*` (live today) |

---

## 6. What is already live (bind, do not rebuild)

These are marked **Gap** in the UI plan but **exist in core today**:

- `GET /network/interfaces`
- `GET /network/interfaces/{iface}`
- `GET /network/ethernet/{iface}/vlan`
- `GET /network/wlan/getInterfaces`
- Full `/network/config/*` suite
- `GET /network/config/status`

First action for UI team: update capability bindings and remove `onUnavailable` flags where the matrix says `bind`.

---

## 7. Testing P0

### 7.1 Matrix approach (confirmed)

Continue the **`namespace_test_matrix` pattern** for P0 APIs. It worked well: positive and negative cases stay visible in a spreadsheet, permutations are explicit, and each row documents what is stubbed.

| Asset | Location |
|-------|----------|
| Scenario spreadsheet | [`tests/scenarios/p0_api_test_matrix.csv`](../tests/scenarios/p0_api_test_matrix.csv) |
| Outcome semantics | [`tests/scenarios/P0_API_OUTCOMES.md`](../tests/scenarios/P0_API_OUTCOMES.md) |
| How-to / mocking policy | [`docs/P0-api-test-matrix.md`](./P0-api-test-matrix.md) |
| Parametrized runner | [`tests/test_p0_api_matrix/`](../tests/test_p0_api_matrix/) |

Handlers are added per endpoint as P0 ships. Rows without handlers skip until implemented.

### 7.2 Mocking policy

| Layer | CI |
|-------|-----|
| FastAPI routing, JWT auth, Pydantic, response shaping | **Real** |
| Service orchestration logic | **Real** |
| **Adapter layout only** (0 / 1 / 2+ monitor) | **Stub** enumeration or `config/status` parse |
| CLI wrappers (`wlanpi-timezone`, `speedtest`, `ip route`, …) | Stub `run_command` fixtures |
| Namespace activate/rollback deep paths | Keep in **`namespace_test_matrix.csv`** — do not duplicate |

On-device integration and fpms2 smoke tests use minimal stubbing.

### 7.3 Scenario coverage (31 rows today)

| Scope | Focus |
|-------|-------|
| **positive** | JWT issue, device info any mode, config status, scan auto-select, mode switch force, timezone, reg-domain, service restart |
| **negative** | Auth missing, mode switch 409 with active config, scan no adapter, disallowed service |
| **deprecate** | Legacy `/network/wlan/*` repurposed off DBus |
| **integration** | fpms2 P0 smoke list |
| **ui-helper** | wlanpi-ui adapter summary translation |

### 7.4 Additional checks

| Check | Method |
|-------|--------|
| OpenAPI schema per new endpoint | Autogenerated `/docs` + contract test |
| Namespace activation | Existing `namespace_test_matrix` (41 rows) |
| wlanpi-ui adapter summary | ui-helper matrix row; mock core HTTP only |
| fpms2 parity | `integration:fpms2_p0_endpoint_smoke` matrix row |

---

## 8. Implementation order (suggested)

1. **Week 1:** ~~`service/restart`; `publicip6`~~ **Done** (see gap matrix `Live` rows)
2. **Week 2:** ~~System primitives (datetime, timezone, reg-domain, battery)~~ **Done** except `timezone/auto`
3. **Network primitives:** ~~routing, tcp/udp, renew, leases, link-stats, wlan drivers~~ **Done**
4. **Wi-Fi/utils workers:** ~~`/utils/wlan/scan`~~ **Done**; ~~speedtest~~ **Done**; cloud-test; **capture** (design: [capture API](./P0-wifi-capture-api.md), [consumer guide](./P0-wifi-capture-consumer-guide.md))
5. **Utils misc:** Blinker, freeradius test, bluetooth pair
6. **System control (last):** Reboot, shutdown, mode switch (with config guard); clients, ssid-passphrase; `timezone/auto`

---

## 9. Decisions (resolved)

| # | Decision | Resolution |
|---|----------|------------|
| 1 | Scan with 0 monitor adapters | **Try managed in root first; 422 `NO_SCAN_ADAPTER` if none suitable** |
| 2 | `force: true` on mode switch | **Yes — auto-deactivate all active configs first; audit log each step** |
| 3 | JWT expiry for panel/mobile | **7 days (existing `ACCESS_TOKEN_EXPIRE_DAYS`); no refresh token in P0** |
| 4 | wlanpi-ui packaging | **Separate package/repo evolved from fpms2**; shared `wlanpi_touch_ui` assets |
| 5 | P0 test approach | **CSV matrix** (`p0_api_test_matrix.csv`); stub **adapter layout only** for hardware permutations |
| 6 | DBus Wi-Fi stack | **Legacy — deprecate**; repurpose `/network/wlan/*` paths; keep systemd DBus for services |

---

*Update `p0-api-gap-matrix.csv` when endpoints ship. Change `verified_status` from `Gap` → `Live` and `p0_action` from `build` → `bind`. Add matrix rows to `p0_api_test_matrix.csv` and handlers in `tests/test_p0_api_matrix/handlers.py`.*
