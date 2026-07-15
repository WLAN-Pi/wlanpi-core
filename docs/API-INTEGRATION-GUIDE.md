# wlanpi-core API integration guide

**Audience:** Application developers, UI platform authors, MCP / AI tool builders  
**OpenAPI:** `/docs` · `/api/v1/openapi.json`  
**Machine export:** `python scripts/export_openapi.py` → `docs/openapi.json`

**Touch-panel alignment:** [APP-OPENAPI-ALIGNMENT.md](./APP-OPENAPI-ALIGNMENT.md) — app vs spec review, pushback on client bugs, missing P0 endpoints.

This guide is a **progressive tutorial**. Each lesson builds on the previous one and includes exact HTTP examples, response fields to parse, and common mistakes.

---

## 0. Before you start

| Concept | Detail |
|---------|--------|
| Base URL | `http://<wlanpi-host>:8000/api/v1` (adjust port if proxied) |
| Auth | Bearer JWT for remote clients; HMAC for localhost services |
| JSON | Many fields are **camelCase** on the wire (`selectedAdapter`, `downloadSpeed`) |
| Device mode | `GET /system/device/info` → `mode` (`classic`, `hotspot`, …) |
| Errors | Plain-text body **or** JSON `{ "error": "CODE", ... }` depending on endpoint |

**Deep-dive supplements**

| Topic | Document |
|-------|----------|
| WLAN scan | [P0-utils-wlan-scan-api.md](./P0-utils-wlan-scan-api.md) |
| Speedtest / reachability | [P0-utils-reachability-speedtest-api.md](./P0-utils-reachability-speedtest-api.md) |
| USB/PCI drivers | [P0-network-wlan-drivers-api.md](./P0-network-wlan-drivers-api.md) |
| Date/time | [P0-system-datetime-api.md](./P0-system-datetime-api.md) |
| Reg domain | [P0-system-reg-domain-api.md](./P0-system-reg-domain-api.md) |
| Deprecated routes | [API-DEPRECATED-ENDPOINTS.md](./API-DEPRECATED-ENDPOINTS.md) |

---

## Lesson 1 — Authenticate

### 1.1 Issue a token

On-device services (touch UI, wlanpi-ui) call this with **localhost HMAC** (`X-Request-Signature`). Remote apps receive a JWT from a device-local pairing flow; they do not bootstrap anonymously over the network.

```http
POST /api/v1/auth/token
Content-Type: application/json
X-Request-Signature: <hmac-sha256-hex>   # on-device only

{ "device_id": "my-app-install-id" }
```

**200 response**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

Store `access_token`. Default lifetime: **7 days**.

### 1.2 Use the token

```http
GET /api/v1/system/device/info
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**401** — missing or expired token. Re-issue via `POST /auth/token`.

### 1.3 Revoke

```http
DELETE /api/v1/auth/token
Authorization: Bearer …
Content-Type: application/json

{ "device_id": "my-app-install-id" }
```

**200 response**

```json
{
  "status": "success",
  "message": "Token revoked",
  "device_id": "my-app-install-id"
}
```

---

## Lesson 2 — Device identity and health

### 2.1 Device info

```http
GET /api/v1/system/device/info
```

| Field | Use |
|-------|-----|
| `model` | Hardware model string |
| `hostname` | FQDN |
| `software_version` | Image version |
| `mode` | **Critical** — gates hotspot-only APIs |

### 2.2 Live stats

```http
GET /api/v1/system/device/stats
```

| Field | Example | Notes |
|-------|---------|-------|
| `ip` | `192.168.1.50` | Primary IPv4 |
| `cpu` | `12%` | Display string |
| `ram` | `1022/3792MB 26%` | |
| `uptime` | `1h 40m` | |

### 2.3 Battery (if present)

```http
GET /api/v1/system/battery
```

`present: false` when no battery — **not an error**.

---

## Lesson 3 — Network information (read-only)

### 3.1 Aggregated document

```http
GET /api/v1/network/info/
```

Large JSON blob: LLDP, CDP, interface summaries, public IPv4. Parse only the sections you need.

### 3.2 Public IPv6

```http
GET /api/v1/network/info/publicip6
```

### 3.3 Reachability (quick health check)

```http
GET /api/v1/utils/reachability
GET /api/v1/utils/reachability?targets=8.8.8.8&targets=1.1.1.1
```

Response uses **labeled keys** (`Ping Google`, `Ping Gateway`, …) plus optional `custom[]` array with structured ping stats.

### 3.4 Network interfaces (iproute2) — not the same as `/network/info`

```http
GET /api/v1/network/interfaces
```

**Shape:** map of string → `IPInterface[]` (arrays of iproute2 JSON objects). There is **no** top-level `interfaces` array.

```json
{
  "eth0": [{ "ifname": "eth0", "operstate": "UP", "addr_info": [] }],
  "wlan0": [{ "ifname": "wlan0", "operstate": "DOWN" }]
}
```

Use `iface["ifname"]` when iterating. For WLAN summary tiles prefer `GET /network/info/` → `wlan_interfaces`. See [APP-OPENAPI-ALIGNMENT.md](./APP-OPENAPI-ALIGNMENT.md).

---

## Lesson 4 — WLAN scan (single shot)

**Canonical endpoint:** `GET /api/v1/utils/wlan/scan`  
**Do not use** `GET /network/wlan/scan` for new code (deprecated wrapper).

```http
GET /api/v1/utils/wlan/scan
GET /api/v1/utils/wlan/scan?iface=wlanpi0&namespace=root
GET /api/v1/utils/wlan/scan?detail=full
```

### Outcomes

| HTTP | Meaning | Client action |
|------|---------|---------------|
| 200 + `networks[]` | Scan completed | Display `networks`; show `selectedAdapter` |
| 200 + `needsSelection: true` | Multiple monitor radios | Show `candidates[]`; retry with `iface` + `namespace` |
| 422 + `NO_SCAN_ADAPTER` | No suitable radio | Show error; check adapter layout |
| 409 | (legacy path only) | Same as needsSelection on old `/network/wlan/scan` |

Full field reference: [P0-utils-wlan-scan-api.md](./P0-utils-wlan-scan-api.md).

---

## Lesson 5 — Network namespace config (multi-step workflow)

**Classic mode only** for activate/deactivate. Check `mode` from Lesson 2.

### 5.1 List configs

```http
GET /api/v1/network/config/
```

Returns map of config id → `true` if active.

### 5.2 Read adapter layout

```http
GET /api/v1/network/config/status
```

Per-namespace `iw dev` view — use for UI adapter summaries.

### 5.3 Create or update config

```http
POST /api/v1/network/config/
Content-Type: application/json

{ "id": "field", "roots": [ … ], "namespaces": [ … ] }
```

See `NETWORK_CONFIG.md` in repo root for NetConfig schema.

### 5.4 Activate (async workflow)

```http
POST /api/v1/network/config/activate/field
```

**200** returns immediately with **provisioned** status — connection continues in background.

**Client workflow:**

```
activate → poll GET /network/config/status every 2s
         → until target iface shows SSID in iw output (or timeout ~60s)
         → show "Connected to {ssid}"
```

### 5.5 Deactivate

```http
POST /api/v1/network/config/deactivate/field
```

Prefer over legacy `POST /network/wlan/revert`.

---

## Lesson 6 — Wi-Fi drivers and PHY info

### 6.1 USB dongles

```http
GET /api/v1/network/wlan/usb-drivers
```

```json
{ "adapters": [ { "interface": "wlan1", "driver": "ath9k_htc", "bus": "usb" } ], "interfaces_scanned": 2 }
```

**Empty `adapters` with `interfaces_scanned > 0` is normal** on PCI-only hardware.

### 6.2 On-board / PCI Wi-Fi

```http
GET /api/v1/network/wlan/pci-drivers
```

### 6.3 PHY capabilities

```http
GET /api/v1/wifi/capabilities
```

Large `adapters[].info` text blobs (`iw phy info`). Cache ~300s in UI jobs.

### 6.4 Regulatory domain

```http
GET /api/v1/system/reg-domain
POST /api/v1/system/reg-domain/set
GET /api/v1/wifi/regulatory
```

---

## Lesson 7 — Hotspot mode (mode-gated)

When `GET /system/device/info` → `mode` is **`hotspot`**:

| Endpoint | Returns |
|----------|---------|
| `GET /system/hotspot/clients` | `{ "count": 2, "interface": "wlan0", "mode": "hotspot" }` |
| `GET /system/hotspot/ssid-passphrase` | `{ "ssid", "passphrase", "mode" }` |
| `GET /wifi/hotspot/stations` | Per-station `iw` dump parsed |
| `GET /wifi/hotspot/link` | Link-focused subset |

**409** when `mode` ≠ `hotspot` — show “Not in hotspot mode”, do not treat as server failure.

---

## Lesson 8 — Long-running HTTP: speedtest

```http
GET /api/v1/utils/speedtest
```

| Expectation | Value |
|-------------|-------|
| Duration | 30–90 seconds typical |
| Client timeout | ≥ 120 seconds |
| UI pattern | Background job + progress indicator |

**200 fields:** `downloadSpeed`, `uploadSpeed`, `pingMs`, `jitterMs`, `ipAddress`, `server`, `testedAt`.

**503** — timeout or LibreSpeed failure (`{ "error": "…" }`).

---

## Lesson 9 — System control

| Action | Endpoint | Notes |
|--------|----------|-------|
| NTP on | `POST /system/timezone/auto` | Returns `{ "ntp": true, "timezone" }` |
| Set TZ | `POST /system/timezone/set` | Body `{ "timezone": "Europe/London" }` |
| Reboot | `POST /system/reboot` | `{ "status": "rebooting" }` — connection drops |
| Shutdown | `POST /system/shutdown` | `{ "status": "shutting_down" }` |
| Service restart | `POST /system/service/restart?name=orb` | Allowed-service gate |

---

## Lesson 10 — Bluetooth and port blinker

```http
POST /api/v1/bluetooth/pair
```

The device removes its existing pairing, enters a 30-second pairing window, and
returns `{ "status": "discoverable", "alias", "message" }`.

- `409 PAIRING_IN_PROGRESS` — another request is starting pairing, or the
  adapter is already in its pairing window.
- `503 BLUETOOTH_UNAVAILABLE` — no Bluetooth adapter is available.
- `503 BLUETOOTH_PAIRING_FAILED` — the old pairing could not be removed or the
  adapter did not become pairable and discoverable.

```http
POST /api/v1/utils/blinker/start?interface=eth0
POST /api/v1/utils/blinker/stop
GET /api/v1/utils/blinker/status
```

Blinker runs until stopped (cable-finder LED pattern on Ethernet).

---

## Lesson 11 — Packet capture WebSocket

**Endpoint:** `WS /api/v1/streaming/capture`

### Workflow

1. Open WebSocket (no auth today — privileged operation).
2. Send JSON commands as **text** frames.
3. Receive JSON **events** and binary **pcapng** data.

### Commands

```json
{ "command": "get_supported_frequencies" }
```

```json
{
  "command": "configure",
  "interfaces": {
    "wlanpi0": { "channels": [36, 40, 44], "dwell": 250 }
  }
}
```

```json
{
  "command": "start",
  "interfaces": ["wlanpi0"],
  "pcap_filter": ""
}
```

```json
{ "command": "stop" }
```

### Event shape (simplified)

```json
{
  "type": "event",
  "category": "error",
  "code": "UNKNOWN_COMMAND",
  "message": "Unsupported command: foo"
}
```

**Planned:** REST session API with token-gated subscriber WebSocket — see `docs/P0-wifi-capture-api.md` (design only).

---

## Lesson 12 — Profiler

```http
GET /api/v1/profiler/status
POST /api/v1/profiler/start
POST /api/v1/profiler/stop
```

Check status before start; stop before starting again.

---

## MCP / AI tool authoring notes

1. **Load schema:** fetch `/api/v1/openapi.json` or use committed `docs/openapi.json` from `scripts/export_openapi.py`.
2. **Always authenticate first** — tool: `auth_token_issue` → store bearer for subsequent tools.
3. **Never call deprecated paths** — use [API-DEPRECATED-ENDPOINTS.md](./API-DEPRECATED-ENDPOINTS.md).
4. **Mode-gated tools** — read `device_info` before hotspot tools; return user-facing message on 409.
5. **Scan tool** — handle three outcomes: networks, needsSelection, NO_SCAN_ADAPTER (see Lesson 4).
6. **Config activate tool** — return after provisioned; document that user must poll `config_status` separately or expose a composite tool.
7. **Speedtest tool** — set tool timeout ≥ 120s; surface 503 errors verbatim.
8. **Field names** — generate clients from OpenAPI models; do not guess snake_case for camelCase fields.

### Suggested tool groups

| Group | Tools |
|-------|-------|
| `device` | info, stats, battery, reboot, shutdown |
| `network` | info, routing, dhcp_leases, config_*, wlan_scan |
| `wifi` | capabilities, regulatory, hotspot_* (if mode=hotspot) |
| `utils` | reachability, speedtest, blinker_* |
| `streaming` | capture_ws (document as long-running session) |

---

## HTTP status quick reference

| Code | Typical meaning in wlanpi-core |
|------|-------------------------------|
| 200 | Success |
| 401 | Auth missing/invalid |
| 409 | Mode conflict or scan needs adapter selection |
| 410 | Deprecated endpoint removed (see body.replacement) |
| 412 | Auth precondition (missing device_id) |
| 422 | Scan: no adapter |
| 503 | Command/hardware unavailable |

---

## Worked example — “Field survey” script (pseudo-code)

```
token = POST /auth/token { device_id }
headers = { Authorization: "Bearer " + token }

info = GET /system/device/info
assert info.mode == "classic"

scan = GET /utils/wlan/scan
if scan.needsSelection:
    pick = user_choose(scan.candidates)
    scan = GET /utils/wlan/scan?iface=pick.iface&namespace=pick.namespace

for network in scan.networks:
    print(network.ssid, network.signal, network.bssid)

reach = GET /utils/reachability
print(reach["Ping Google"], reach["Browse Google"])
```

---

*Update this guide when new endpoints ship. Keep OpenAPI summaries in sync via `wlanpi_core/api/openapi_docs.py`.*
