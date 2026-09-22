## Problem statement

WLAN Pi needs one architecture that drives every control surface: built-in panel (OLED today, TFT tomorrow), mobile app, WebUI, Cockpit/TUI, and future clients. Two requirements conflict if handled naively:

1. **Multi-client sync** — navigate on the panel, see the same screen on the phone.
2. **Clean system boundaries** — hardware and privileged operations must stay centralised and testable.

Today, ~39 of 97 touch-menu capabilities work via direct core REST. **58 are marked unavailable** in the mobile app. fpms2 partially fills gaps via shell scripts, but that does not scale to Flutter/LVGL/WebUI clients.

Recent **namespace work** in `wlanpi-core` adds substantial adapter management (PHY moves, wpa_supplicant in namespaces, config activate/deactivate, async connection monitoring). This capability is mostly **internal** — correct for safety — but the UI platform needs **structured worker primitives** to orchestrate it, not raw access to namespace internals.

**Related docs:** `/home/wlanpi/docs/UI-plan.md` (UI platform architecture), `NETWORK_CONFIG.md` (namespace config system).

---

## Proposed architecture (approved with clarifications)

The UI team's **two services, four channels** model is adopted. Core owns system work; the UI platform owns presentation orchestration.

```
┌─────────────────────────────────────────────────────────────────┐
│  Thin clients: OLED / LVGL / Flutter / TUI / Mobile / WebUI   │
└────────┬──────────────────┬─────────────────────┬───────────────┘
         │ ① Session WS/REST│ ② Job WS            │ ③ UI REST
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  wlanpi-ui  (evolved from fpms2)                                │
│  • touch_menu.v1.json, capabilities.*.json                    │
│  • UiSession store (nav, view, revision, complications)         │
│  • Job orchestrator (freshnessSec, dedup, fan-out)              │
│  • Capability → core worker bindings                            │
└────────────────────────────┬────────────────────────────────────┘
                             │ ④ Core REST only
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  wlanpi-core  (worker / arbiter)                                │
│  • Hardware, namespaces, systemd, scripts                       │
│  • Structured query/action primitives                           │
│  • NO menu JSON, NO session state, NO UI revision               │
└─────────────────────────────────────────────────────────────────┘
```

### Authority decisions (core team)

| Topic | UI team proposal | Decision |
|-------|------------------|----------|
| Separate UI platform service | Yes (`wlanpi-ui`) | **Accepted** — required for multi-client sync |
| WebSockets for session sync | UI platform `/ui/ws` | **Accepted** — does not belong in core |
| WebSockets for job streaming | UI platform `/ui/jobs/{id}/ws` | **Accepted** — scans, speedtest, capture |
| WebSockets in core | Not proposed | **Only existing capture stream** (`/api/v1/streaming/capture`) until migrated; no session/job WS in core |
| Job freshness / dedup | UI platform | **Accepted** — core runs worker once per request; UI platform caches |
| Menu JSON in core | Must not | **Accepted** |
| Generic `POST /worker/run` | Open question | **Rejected** — specific REST endpoints per domain for OpenAPI, auth, and testing |
| Direct core REST from mobile cards | Optional | **Accepted** for admin-style card views; panel experience goes through `wlanpi-ui` |
| Namespace PHY/interface moves as API | Not proposed | **Rejected** — stays internal; UI uses `/network/config/activate` and status queries |

### What each layer owns

**wlanpi-ui owns:**
- Menu and capability metadata (`GET /ui/menu`, `/ui/capabilities/*`)
- `UiSession` (revision, nav, view, loading, homepage, complications)
- Session WebSocket (bidirectional: input + state push)
- Job lifecycle (`POST /ui/jobs/run` with `freshnessSec`, job WS, cancel)
- Mapping 97 capabilities → core worker calls

**wlanpi-core owns:**
- Device/system queries and privileged actions
- Network namespace config CRUD and activation (`/network/config/*`)
- Wi-Fi scan/connect **primitives** (namespace-aware)
- Service control, profiler, bluetooth, utils
- Existing packet capture WebSocket (wrapped by UI platform as a job)

---

## Gap analysis corrections

The UI plan §12.2 marks several endpoints as **Gap** that **already exist**. These should be rebinding work in `wlanpi-ui`, not new core development:

| Core path | UI plan status | Actual status |
|-----------|----------------|---------------|
| `GET /network/interfaces` | Gap | **Live** |
| `GET /network/interfaces/{iface}` | Gap | **Live** |
| `GET /network/ethernet/{iface}/vlan` | Gap | **Live** |
| `GET /network/wlan/getInterfaces` | Gap | **Live** |
| `GET /network/wlan/scan` | — (plan proposes `/utils/wlan/scan`) | **Live** (DBus wpa_supplicant, root namespace) |
| `GET /network/config/status` | Not listed | **Live** — namespace-aware adapter view via `iw dev` |
| `GET /network/config/*` | Not listed | **Live** — full config CRUD + activate/deactivate |
| `WS /streaming/capture` | Plan proposes REST capture | **Live** — needs REST start/stop wrappers for job orchestration |

**Namespace note:** Config activation returns `"provisioned"` immediately; `ConnectionMonitor` completes connection asynchronously. The UI platform should poll core status (or subscribe via job WS wrapping a status poll loop) — not expect synchronous `"connected"`.

---

## Core worker API — what to build

Grouped by priority. Paths use `/api/v1` prefix.

### P0 — unblocks fpms2 parity and touch menu (58 gaps)

#### System

| Method | Path | Notes |
|--------|------|-------|
| GET | `/system/battery` | UPS/HAT if present |
| GET | `/system/datetime` | Current date/time |
| GET | `/system/timezone` | Current TZ |
| GET | `/system/timezone/list` | Available zones |
| POST | `/system/timezone/set` | Body `{timezone}` — wraps `wlanpi-timezone` |
| POST | `/system/timezone/auto` | NTP auto |
| GET | `/system/reg-domain` | Wraps `wlanpi-reg-domain` |
| GET | `/system/reg-domain/list` | Supported country codes from wireless-regdb |
| POST | `/system/reg-domain/set` | Body `{country}` |
| POST | `/system/reboot` | Auth-gated |
| POST | `/system/shutdown` | Auth-gated |
| POST | `/system/mode/switch` | Body `{mode}` — wraps mode switcher scripts; **must interact safely with namespace configs** |
| GET | `/system/clients` | Hotspot client count |
| GET | `/system/ssid-passphrase` | Hotspot/profiler creds |

#### Network

| Method | Path | Notes |
|--------|------|-------|
| GET | `/network/info/publicip6` | IPv6 variant (v4 already in `/network/info/`) |
| GET | `/network/routing` | `ip route` structured |
| GET | `/network/connections/tcp` | Active TCP |
| GET | `/network/connections/udp` | Active UDP |
| POST | `/network/interfaces/{iface}/renew` | dhclient renew |
| GET | `/network/dhcp/leases` | Lease file parse |
| GET | `/network/interfaces/{iface}/link-stats` | ethtool |
| GET | `/network/wlan/usb-drivers` | USB Wi-Fi driver info |
| GET | `/network/wlan/pci-drivers` | PCI Wi-Fi driver info |

#### Wi-Fi workers (UI platform wraps as jobs with `freshnessSec`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/utils/wlan/scan` | **New canonical scan primitive** — namespace-aware via query `?iface=&namespace=`; supersedes `/network/wlan/scan` for UI use |
| GET | `/wifi/capabilities` | `iw phy` capabilities — cacheable (job freshness ~300s) |
| GET | `/wifi/regulatory` | Regulatory domain info |
| GET | `/wifi/client/stations` | AP mode stations |
| GET | `/wifi/client/link` | Client link stats |
| POST | `/wifi/monitor/enable` | Destructive — mode change |
| POST | `/wifi/monitor/disable` | Restore managed |

#### Utils workers

| Method | Path | Notes |
|--------|------|-------|
| GET | `/utils/speedtest` | Long-running — UI job wrapper, freshness ~10s |
| GET | `/utils/cloud-test/{vendor}` | Per-vendor reachability |
| POST | `/utils/blinker/start` | Restore port blinker |
| POST | `/utils/blinker/stop` | |
| GET | `/utils/blinker/status` | |
| POST | `/utils/freeradius/test` | |

#### Services (small addition)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/system/service/restart?name=` | Missing today (only start/stop) |

#### Bluetooth

| Method | Path | Notes |
|--------|------|-------|
| POST | `/bluetooth/pair` | Pairing primitive |

#### Capture (bridge existing WebSocket to job model)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/wifi/capture/start` | Start capture session, return session id |
| POST | `/wifi/capture/stop` | Stop capture |
| GET | `/wifi/capture/status` | Running state |
| GET | `/wifi/capture/files` | Output file list |

### P1 — apps and namespace-aware features

| Method | Path | Notes |
|--------|------|-------|
| GET | `/network/adapters` | **New** — PHY ↔ interface ↔ namespace map (wraps internal `adapters/` + `network/config/status`) |
| GET | `/network/adapters/{iface}/connection` | **New** — wpa_state, SSID, IP (wraps `wpa/status.get_wpa_status`) |
| POST | `/profiler/purge/reports` | fpms2 parity |
| POST | `/profiler/purge/files` | |
| GET | `/profiler/profiles` | List profile files |
| GET | `/scanner/files` | pcap/csv paths |
| POST | `/scanner/scan/csv` | CSV scan export |
| POST | `/scanner/capture/start` | May delegate to capture primitives |
| POST | `/scanner/capture/stop` | |
| GET | `/orb/wifi/interface` | Netns interface for orb-wifi |
| POST | `/orb/reset-identity` | Destructive |
| GET | `/system/updates` | Package updates check |
| POST | `/system/updates/install` | Long-running — UI job only |

### Explicitly NOT building in core

- Session WebSocket, job WebSocket, menu serving
- Job freshness cache
- `UiSession`, revision counters, complications layout
- Raw namespace manipulation (PHY move, interface create/delete)
- Display orientation (UI-only)

---

## Namespace integration (for reviewers)

The namespace system is the **correct** way for the UI to connect Wi-Fi adapters to networks. Internally, activation:

1. Validates config JSON
2. Creates namespace if needed, moves PHY, creates interface
3. Starts wpa_supplicant
4. Returns `"provisioned"` immediately
5. Background `ConnectionMonitor` completes DHCP, routing, autostart app

**UI platform bindings** should map capabilities like "connect to network" to:

- `POST /network/config/` (create/save config) + `POST /network/config/activate/{id}`, or
- A future simplified `POST /network/wifi/connect` primitive (P1) that wraps the same service layer

The UI never calls `_prepare_namespace()` or `iw phy set netns` directly.

---

## Auth model

| Caller | Auth |
|--------|------|
| wlanpi-ui → wlanpi-core | Localhost HMAC (existing `verify_hmac`) |
| Remote mobile/WebUI → wlanpi-ui | JWT or session token (UI platform concern) |
| Admin tools → wlanpi-core | JWT (existing) |

Remote clients authenticate to **wlanpi-ui only**; they do not need direct core access for panel sync.

---

## Success criteria

- [ ] Menu JSON served from `wlanpi-ui`; core has no `/touch-ui` or `/ui/menu` routes
- [ ] Navigate on built-in display; mobile shows same `UiSession.revision`
- [ ] Two speedtest requests within 10s → one core run (UI platform cache)
- [ ] Wi-Fi scan: job WS streams BSS lines; cancel on same socket; session WS stays small
- [ ] fpms2 `test_endpoints.py` equivalent green against core P0 endpoints
- [ ] Core OpenAPI documents worker primitives only
- [ ] Namespace connect flow works through config system without exposing internals

---

## Risks

| Risk | Mitigation |
|------|------------|
| Mode switch while namespace config active | Core validates mode switch; deactivate configs or refuse with clear error |
| `/network/wlan/set` hardcoded `"testns"` | Deprecate; UI uses config system exclusively |
| Capture WebSocket has no auth today | Add HMAC before UI platform exposes capture jobs |
| Two scan endpoints (`/network/wlan/scan` vs `/utils/wlan/scan`) | New canonical path; old path deprecated in docs |
| Job cache lost on reboot | Accept in-memory for P0; sqlite optional P1 (UI platform decision) |

---

## Related work

- **UI platform:** separate feature in fpms2 / `wlanpi-ui` repo (session WS, job runner, menu serving)
- **Namespace hardening:** async `ConnectionMonitor`, classic mode gate, credential redaction (recent)
- **Branch:** `feature/new-apis` (intended landing branch)

---

## Open questions

1. **Repo packaging:** `wlanpi-ui` as separate GitHub repo (evolved from fpms2) vs monorepo package — recommend **separate repo**, shared `wlanpi_touch_ui` assets package.
2. **Simplified Wi-Fi connect:** Build `POST /network/wifi/connect` in core P1, or keep config CRUD only?
3. **Mobile card menu:** Stay on direct core REST permanently, or migrate to wlanpi-ui for consistency?
4. **Capture migration:** Keep core WebSocket for binary stream with UI platform job WS as proxy, or move stream to UI platform long-term?
