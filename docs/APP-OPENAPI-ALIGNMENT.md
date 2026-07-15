# Touch-panel app vs OpenAPI alignment

**Purpose:** Reconcile the wlanpi-ui / touch-panel implementation with `docs/openapi.json` (exported from wlanpi-core on `feature/new-apis`).  
**Audience:** App authors, core maintainers, MCP tool builders.

> **Important:** Several items in early app reviews were checked against an **outdated** OpenAPI export (~15 paths). The current export has **68 path entries** and documents most P0 workers the touch panel uses. Gaps that remain are **planned-but-not-built** endpoints (mode switch, cloud-test, freeradius, touch-ui manifest, REST capture), not documentation omissions.

Regenerate after core changes:

```bash
python scripts/export_openapi.py
```

---

## Executive summary

| Verdict | Detail |
|---------|--------|
| **App scan path** | **Correct** — `GET /utils/wlan/scan` is canonical. Do not point scanner UI at `/network/wlan/scan`. |
| **App reachability / speedtest** | **Correct paths** — both are in OpenAPI with typed schemas. |
| **App `fetchWifiInterfaces()`** | **Bug in app** — parses `response['interfaces']` from `GET /network/interfaces`; OpenAPI shape is `Record<string, IPInterface[]>`. Profiler page already parses correctly. |
| **OpenAPI vs 2.1.7 image** | Current branch is **ahead** of 2.1.7; treat this repo’s export as source of truth until released. |
| **Still not in core** | `POST /system/mode/switch`, `GET /utils/cloud-test/{vendor}`, `POST /utils/freeradius/test`, `/touch-ui/*`, REST PCAP session API. |

---

## What aligns well (app is right)

These touch-panel usages match live core + OpenAPI:

| Area | OpenAPI path | App / capability | Notes |
|------|--------------|------------------|-------|
| Network info | `GET /network/info/` | `NetworkInfoFormatter` | Nested shapes now typed in OpenAPI (`InterfaceSummary`, `WlanInterfaceSummary`, `InfoLinesSection`). |
| Reachability | `GET /utils/reachability` | `panel_action_executor.dart` | Flat keys + `custom[]` documented; `targets` query param in spec. |
| USB / UFW | `GET /utils/usb`, `/ufw` | Schema widgets | Trailing slash on `/network/info/` tolerated by FastAPI. |
| Device | `GET /system/device/info`, `/stats` | Touch panel providers | |
| Services | `GET/POST /system/service/{status,start,stop,restart}` | `PanelActionExecutor` | App emulates restart via stop+start where needed; core also exposes `restart`. |
| Bluetooth | `GET /status`, `POST /power/{action}`, `POST /pair` | capabilities | Power actions `on` / `off`. |
| Profiler | `GET /status`, `POST /start`, `/stop` | Apps page | |
| NetConfig | `/network/config/*` | `network_config_service.dart` | |
| **WLAN scan** | `GET /utils/wlan/scan` | `wlanScanEndpoint` | **Canonical** — enriched `networks[]`, `selectedAdapter`, `needsSelection`. |
| **Speedtest** | `GET /utils/speedtest` | `speedtestEndpoint` | Present in OpenAPI (`SpeedTest` schema). |
| Network primitives | `/network/routing`, `/connections/*`, `/dhcp/leases`, link-stats, renew, wlan drivers | capabilities P0 | All in current export. |
| System control | reboot, shutdown, datetime, timezone/*, reg-domain/*, hotspot reads | capabilities P0 | In export; hotspot routes document **409** outside hotspot mode. |
| Wi-Fi | `/wifi/capabilities`, `/regulatory`, `/hotspot/stations`, `/hotspot/link` | capabilities P0 | In export. |
| Utils | blinker start/stop/status | capabilities | In export. |

---

## Critical clarifications (not core bugs)

### 1. Two WLAN scan APIs — app picked the right one

| | **Canonical** `GET /utils/wlan/scan` | **Deprecated** `GET /network/wlan/scan` |
|---|--------------------------------------|----------------------------------------|
| Tag | `device utils` | `deprecated` |
| Query | `iface`, `namespace`, `hidden`, `detail` | `type` (ignored), `interface` |
| Response | `networks[]`, `selectedAdapter`, `needsSelection`, `candidates`, `scannedAt`, RF extensions | Legacy `nets[]` (`ScanItem`) |
| Multi-adapter | **200** + `needsSelection: true` | **409** + `NEEDS_SELECTION` |

The scanner capability (`app.scanner.scan`) **must** keep using `/utils/wlan/scan`. The legacy path exists only for old clients.

### 2. Speedtest is documented

`GET /utils/speedtest` is in OpenAPI with `SpeedTest` fields: `ipAddress`, `downloadSpeed`, `uploadSpeed`, `pingMs`, `jitterMs`, `server`, `testedAt`. Failures return **503** with `{ "error": "…" }`.

### 3. Reachability extensions are documented

OpenAPI includes:

- Query `targets` (repeat or comma-separated, max 10)
- Response `custom[]` with `target`, `success`, `rttMsMin`, `rttMsAvg`, `rttMsMax`, `packetLossPercent`, `display`
- Error bodies **400** / **503** with `{ "error": "…" }`

Built-in keys (`Ping Google`, `Browse Google`, …) remain the stable fpms2 binding surface.

### 4. JWT bootstrap — app must use localhost HMAC

`POST /auth/token` does **not** require a pre-existing Bearer token in OpenAPI (security: HMAC or none). Runtime behaviour:

- **On-device** callers: `X-Request-Signature` HMAC from localhost.
- **Remote** HTTP without HMAC: **401** unless a Bearer is already present.

Remote apps obtain the first JWT through a **device-local pairing/proxy** step (touch UI on the Pi), not by calling token issue from the internet directly. See [API-INTEGRATION-GUIDE.md](./API-INTEGRATION-GUIDE.md) §1.

---

## App bugs / misinterpretations (pushback)

### `fetchWifiInterfaces()` wrong response shape

**OpenAPI** for `GET /network/interfaces`:

```json
{
  "eth0": [ { "ifname": "eth0", "operstate": "UP", … } ],
  "wlan0": [ { "ifname": "wlan0", … } ]
}
```

Top-level keys are **namespace or grouping keys**; each value is an **`IPInterface[]` array**, not a flat `interfaces` property.

**Fix (app):** Parse like `apps_page_widget.dart` (iterate map entries, read `iface['ifname']`), or use:

- `GET /network/info/` → `wlan_interfaces` for summary cards, or
- `GET /network/config/status` for namespace-aware `iw dev` layout.

### Expecting `interfaces` inside `/network/interfaces`

There is no `{ "interfaces": […] }` wrapper on this route. That shape belongs to deprecated `GET /network/wlan/getInterfaces` (`{ "interfaces": [{ "interface": "wlan0" }] }`).

### Service restart

App pattern `stop` + `start` is valid. Core also exposes `POST /system/service/restart?name=` — either approach is fine.

### Bluetooth power paths

Capabilities may list `/power/on` and `/power/off`; OpenAPI documents `POST /bluetooth/power/{action}` with `action` ∈ `on|off`. Equivalent.

---

## Genuinely missing from core (not in OpenAPI yet)

These appear in `docs/touch_ui_backend_development_plan.md` / `capabilities.app.v1.json` but are **not implemented** in wlanpi-core on this branch:

| Endpoint | Status |
|----------|--------|
| `POST /system/mode/switch` | Planned P0 — 409 when namespace config active unless `force` |
| `GET /utils/cloud-test/{vendor}` | Planned P0 |
| `POST /utils/freeradius/test` | Planned P0 |
| `/touch-ui/menu`, `/touch-ui/capabilities/shared`, `/touch-ui/manifest` | **By design in wlanpi-ui**, not core |
| REST scanner PCAP/CSV/files | Planned — WebSocket `/streaming/capture` exists today |

Do not treat absence from OpenAPI as “app wrong” for these — core work is still open. See [p0-api-gap-matrix.csv](./p0-api-gap-matrix.csv).

---

## OpenAPI quality fixes (this branch)

| Issue | Resolution |
|-------|------------|
| `POST /auth/token` showed `HTTPBearer` required | OpenAPI now documents HMAC / optional security; description explains bootstrap |
| Empty / weak error schemas on utils | 400/503 on reachability & scan; 503 body on speedtest |
| Boolean examples as strings (profiler) | Fixed to `true`/`false` |
| Untyped `NetworkInfo` | Nested models for interface summaries and `info[]` sections |
| Legacy WLAN in `network` tag | Moved to dedicated **`deprecated`** tag; 410-only routes document **410** only |
| Path param nullable (`/ethernet/{interface}`) | Path param typed as required `string` |

Remaining known limitations:

- **Combined VLAN routes** still share handlers; some optional path params may look nullable in OpenAPI — prefer the documented canonical path for each operation.
- **`NetworkInfo.interfaces`** may contain a top-level `"error"` string key on failure — union typing documents this.

---

## Canonical reference map for app authors

| Use case | Call |
|----------|------|
| Scanner UI | `GET /utils/wlan/scan` |
| Legacy fpms scan binding | Migrate to utils path |
| Interface list (iproute2) | `GET /network/interfaces` — parse map of `IPInterface[]` |
| WLAN summary tiles | `GET /network/info/` → `wlan_interfaces` |
| Namespace / wpa state | `GET /network/config/status` |
| Connect / activate Wi-Fi | `POST /network/config/` + `activate/{id}` |
| Deprecated connect | `POST /network/wlan/set-dbus` → **410** |

---

## Related docs

- [API-INTEGRATION-GUIDE.md](./API-INTEGRATION-GUIDE.md) — worked HTTP examples
- [API-DEPRECATED-ENDPOINTS.md](./API-DEPRECATED-ENDPOINTS.md) — legacy WLAN migration
- [P0-utils-wlan-scan-api.md](./P0-utils-wlan-scan-api.md) — scan field reference
- [P0-utils-reachability-speedtest-api.md](./P0-utils-reachability-speedtest-api.md) — reachability & speedtest
