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
| Base URL | Production: `https://<wlanpi-host>:31415/api/v1` · Dev loopback: `http://127.0.0.1:8000/api/v1` |
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

## TLS and certificate trust

The production API is HTTPS-only on port 31415 via nginx. There is no cleartext
fallback. Direct development runs on `http://127.0.0.1:8000` (loopback only)
and is not a substitute for the packaged API.

**Self-signed certificate.** The device certificate at
`/etc/nginx/ssl/self-signed-wlanpi.cert` is its own CA. Every client must pin
this file; it is both the leaf certificate and the trust anchor.

On each connection the client checks three things: (1) the presented certificate
matches the pinned file, (2) the connection target appears in the SANs
(`localhost`, `wlanpi.local`, `127.0.0.1`, `198.18.42.1`), and (3) the current
date is inside the validity window. Any failure kills the connection before API
data flows.

**Per-client setup:**

| Client | Configuration |
|--------|---------------|
| Python Requests | `verify="/etc/nginx/ssl/self-signed-wlanpi.cert"` |
| curl | `--cacert /etc/nginx/ssl/self-signed-wlanpi.cert` |
| HTTPX | explicit `ssl_context` or `SSL_CERT_FILE` environment variable |
| Firefox on device | already imported by `wlanpi-firefox-setup` — no action needed |

Never use `verify=False`, `curl -k`, or an automatic HTTP fallback in
production.

**Remote clients** must import the certificate once before connecting. A
hostname or IP outside the four SANs produces a hostname mismatch error. A
client that has not imported the certificate receives an untrusted error and
cannot proceed without bypassing verification — which authenticates nothing.

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

Token lifetime depends on the boot in which Core issued it:

| Scenario | Result |
|---|---|
| Same boot, including a wall-clock correction | Valid until its monotonic lifetime ends |
| Previous boot, restored clock is within the signed `iat` to `exp` window | Valid |
| Previous boot, restored clock is more than 30 seconds behind `iat` | `503 AUTH_CLOCK_NOT_SET` |
| At or after monotonic expiry on the same boot, or `exp` after reboot | `401` |

The clock error has one exact body:

```http
HTTP/1.1 503 Service Unavailable
Content-Type: application/json

{"error":"AUTH_CLOCK_NOT_SET","message":"NTP needs set; cannot proceed"}
```

When you receive this error, keep the token and retry it after an
operator-controlled time synchronization. Do not treat every 503 as a clock
error, and do not retry automatically. The unchanged token is evaluated normally
after the clock catches up.

**401** means the token is missing, malformed, revoked, or expired. Re-issue via
`POST /auth/token` when appropriate.

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
| 409 + `SCAN_IN_PROGRESS` | Same adapter already scanning | Coalesce / short retry — **not** adapter selection |
| 409 + `NEEDS_SELECTION` | Legacy `/network/wlan/scan` only | Same as needsSelection; prefer canonical path |

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

Live Wi-Fi capture: send JSON **text** commands, receive JSON **events** and
binary **pcapng** frames. One authenticated connection owns a capture; other
authenticated connections can subscribe to it read-only.

> The production URL is
> `wss://<host>:31415/api/v1/streaming/capture`. Tokens go in the first message,
> **never** in the URL (query strings are logged; a `?token=` connection is
> refused with close code 4401).

### 11.1 Authenticate (first message, required)

The first frame MUST authenticate within 10 seconds, or the socket closes with
code **4401**:

```json
{ "command": "auth", "token": "<core JWT from Lesson 1>" }
```

Reply: `{"type":"event","event":"status","code":"AUTH_OK","data":{"did":"…"}}`.
An invalid/expired token, a non-auth first message, or a timeout closes 4401.

### 11.2 Own a capture

```json
{ "command": "configure",
  "interfaces": { "wlanpi0": { "channels": [{"freq": 5180, "width": 20}],
                               "dwell_time": 250 } } }
```

```json
{ "command": "start", "interfaces": ["wlanpi0"], "pcap_filter": "" }
```

`width` ∈ {20,40,80,160}; `dwell_time` 50–60000 ms. Interface names are the
monitor VIFs (`wlanpiN`); core runs the capture in whatever namespace the
adapter lives in. `start` replies `CAPTURE_STARTED` with a `session_id`
(`cap_xxxx`), the `interfaces`, the `namespace`, and the requested `config`.
Then binary pcapng frames stream until `{ "command": "stop" }`, the socket
closes, or the capture ends (`CAPTURE_ENDED`). Only the owning connection can
`configure`/`stop`.

### 11.3 Subscribe to someone else's capture (read-only)

Discover running captures, then attach — you do **not** need the owner's
command or `session_id` in advance:

```json
{ "command": "list_sessions" }
```

Reply `SESSIONS` lists each capture with `session_id`, `owner`, `interfaces`,
`namespace`, and `config`. Pick the one on the interface you want (one owner
per interface) and:

```json
{ "command": "subscribe", "session_id": "cap_ab12cd34" }
```

`SUBSCRIBED` returns that session's `config` (so you know the channels/filter
you are receiving), then the same binary pcapng stream arrives. A subscriber
cannot control the capture; `{ "command": "unsubscribe" }` detaches. When the
owner stops or disconnects, subscribers get `CAPTURE_STOPPED`/`CAPTURE_ENDED`.
A subscriber that cannot keep up with the stream is closed with code 1013.

### 11.4 Other commands & events

`{ "command": "get_supported_frequencies" }` → `SUPPORTED_FREQUENCIES` (channel
list per capture adapter). Event shape:

```json
{ "type": "event", "event": "status", "code": "CAPTURE_STARTED",
  "data": { "session_id": "cap_ab12", "interfaces": ["wlanpi0"],
            "namespace": null, "config": { … } } }
```

Notable codes: `AUTH_OK`, `AUTH_FAILED`, `CAPTURE_STARTED`, `CHANNEL_SET` /
`CHANNEL_SET_FAILED` (hop status; the failure message carries the `iw` reason —
on single-radio devices the phy can be briefly busy while the managed interface
scans), `SUBSCRIBED`, `SESSIONS`, `UNSUBSCRIBED`, `CAPTURE_STOPPED`,
`CAPTURE_ENDED`, and errors `INTERFACE_IN_USE`, `INTERFACE_NOT_AVAILABLE`,
`SESSION_NOT_FOUND`, `CONFIG_INVALID`, `UNKNOWN_COMMAND`.

**Reference client:** `tools/capture_harness/` implements this whole flow
(owner, subscriber-by-interface, and pcapng dissection). **MCP integration:**
`docs/capture-ws-mcp-handover.md`.

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
2. **Configure TLS** — set `WLANPI_CORE_URL=https://localhost:31415` and
   `WLANPI_CORE_CA=/etc/nginx/ssl/self-signed-wlanpi.cert` before connecting.
   Pass the CA file explicitly to the HTTP client; never disable verification.
3. **Always authenticate first** — tool: `auth_token_issue` → store bearer for subsequent tools.
3. **Never call deprecated paths** — use [API-DEPRECATED-ENDPOINTS.md](./API-DEPRECATED-ENDPOINTS.md).
4. **Mode-gated tools** — read `device_info` before hotspot tools; return user-facing message on 409.
5. **Scan tool** — handle four outcomes: networks, needsSelection, `NO_SCAN_ADAPTER`, `SCAN_IN_PROGRESS` (see Lesson 4).
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
| 409 | Mode conflict; scan `SCAN_IN_PROGRESS`; Bluetooth `PAIRING_IN_PROGRESS`; legacy scan `NEEDS_SELECTION` — always read JSON `error` |
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
