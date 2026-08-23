# WiFi packet capture — core API design

**Status:** Design (P0 — implementation pending)  
**Version:** 2026.06.14  
**Audience:** wlanpi-core implementers, MCP tool authors, OpenAPI maintainers

**Related:**
- [Application developer guide](./P0-wifi-capture-consumer-guide.md) — how to build controllers and subscribers
- [P0 core worker API](./P0-core-worker-api.md) §2.4.1, Stream D
- [WLAN scan API](./P0-utils-wlan-scan-api.md) — snapshot scan (not continuous capture)
- [Gap matrix](./p0-api-gap-matrix.csv)
- **Existing (legacy):** `WS /api/v1/streaming/capture` — to be wrapped and extended by this design

---

## 1. Purpose

Provide **namespace-aware, multi-source WiFi packet capture** with:

1. **Discovery** — any app can list capture-capable interfaces without understanding namespaces
2. **Control** — one authenticated **controller** per session (start/stop, channels, filters)
3. **Data** — many **subscribers** can consume capture output (secure by default)
4. **MCP / AI** — **`summary` mode** first: parsed frame JSON over REST (no raw pcap required)

Passive capture uses monitor-mode interfaces, `dumpcap`, channel hopping, and optional BPF filters. Channel attribution uses **Radiotap** fields in each frame; core also emits **channel-change events** on the WebSocket text channel.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  REST — discovery, session control, summary frames (MCP)         │
│  GET  /wifi/capture/sources                                      │
│  POST /wifi/capture/sessions                                     │
│  GET  /wifi/capture/sessions/{id}                                │
│  PATCH /wifi/capture/sessions/{id}                               │
│  POST /wifi/capture/sessions/{id}/stop                           │
│  GET  /wifi/capture/sessions/{id}/frames                         │
│  GET  /wifi/capture/sessions/{id}/files                          │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│  Session hub (core) — one control lease, N subscribers           │
│  Per source: ns_exec(dumpcap), ns_exec(iw set freq), hop loop     │
└────────────────────────────┬─────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
  WS subscribers        MCP poll /frames     File sink (optional)
  pcapng bytes          summary JSON         GET .../files
  + JSON events
```

| Plane | Protocol | Auth |
|-------|----------|------|
| Discovery | REST | JWT / HMAC (required) |
| Control | REST | JWT / HMAC + **control token** (session-scoped) |
| Summary data (MCP) | REST | JWT / HMAC + control or read token |
| Stream data | WebSocket | **Subscribe token** (required unless session explicitly public) |

**Design rule:** REST orchestrates jobs; WebSocket carries **live pcap bytes** and **low-latency events**. MCP uses **summary mode only** in P0 — no WebSocket required for AI tools.

---

## 3. Capture modes

| Mode | P0 | Data path | Primary consumer |
|------|-----|-----------|------------------|
| **`summary`** | **Yes (default for MCP)** | `GET .../frames` returns parsed JSON | MCP, AI agents, lightweight apps |
| **`stream`** | Yes | `WS .../streaming/capture?session=…&token=…` pcapng | Wireshark, scanner UI, advanced tools |
| **`file`** | Optional P0 | Written pcap on disk; `GET .../files` | Long captures, post-processing |

Session `mode` is set at create time. P0 MCP tools use **`summary` only**.

---

## 4. Discovery — `GET /api/v1/wifi/capture/sources`

Any app (including one that did **not** create network namespaces) calls this first. Core resolves namespaces internally using the same underlying view as `GET /network/config/status` plus connection state from `wpa_cli status`.

### 4.1 Request

```
GET /api/v1/wifi/capture/sources
```

No query parameters required. Optional `namespace` filter for advanced tools only — **not required** for normal apps.

### 4.2 Response (`200`)

```json
{
  "sources": [
    {
      "sourceId": "root/wlanpi0",
      "iface": "wlanpi0",
      "namespace": "root",
      "label": "wlanpi0 — monitor, ready",
      "mode": "monitor",
      "captureReady": true,
      "usable": true,
      "risk": "none",
      "connected": false,
      "connectedSsid": null,
      "alternatives": []
    },
    {
      "sourceId": "root/wlan0",
      "iface": "wlan0",
      "namespace": "root",
      "label": "wlan0 — managed, connected to OfficeWiFi",
      "mode": "managed",
      "captureReady": false,
      "usable": false,
      "risk": "disrupts_connection",
      "connected": true,
      "connectedSsid": "OfficeWiFi",
      "alternatives": [
        {
          "action": "use_sibling_monitor",
          "sourceId": "root/wlanpi0",
          "label": "Use wlanpi0 (monitor) on same radio"
        }
      ]
    },
    {
      "sourceId": "scan_ns/wlanpi1",
      "iface": "wlanpi1",
      "namespace": "scan_ns",
      "label": "wlanpi1 — monitor (scan_ns)",
      "mode": "monitor",
      "captureReady": true,
      "usable": true,
      "risk": "none",
      "connected": false,
      "connectedSsid": null,
      "alternatives": []
    }
  ],
  "needsSelection": false
}
```

### 4.3 Field semantics

| Field | Meaning |
|-------|---------|
| `sourceId` | Stable handle for session APIs: `{namespace}/{iface}` (`root/…` for default namespace) |
| `captureReady` | Monitor VIF exists; core can run `dumpcap` now |
| `usable` | Safe to select **without** extra flags |
| `risk` | `none` \| `disrupts_connection` \| `requires_mode_change` \| `namespace_busy` |
| `connected` | Interface is associated to an AP (managed + active connection) |
| `alternatives` | Safer options — prefer `use_sibling_monitor` when present |

### 4.4 Usability rules (core-enforced)

| Situation | `usable` | `risk` | Notes |
|-----------|----------|--------|-------|
| Monitor VIF, not connected | `true` | `none` | Default capture path |
| Managed, **connected** to AP | `false` | `disrupts_connection` | Capture/channel hop would drop Wi‑Fi link |
| Managed, not connected | `false` | `requires_mode_change` | May need monitor VIF created on same PHY |
| PHY owned by active namespace config | `false` | `namespace_busy` | Another profile holds the radio |

**Connected managed interfaces:** A **managed** interface with an active Wi‑Fi connection (`wpa_state=COMPLETED`) is **not usable by default**. Starting capture or aggressive channel hopping on that interface would disrupt the connection. Core **blocks** this unless the controller passes **`allowDisruptive: true`** (see §5.2). Apps should prefer a **monitor sibling** (`wlanpi0`) when `alternatives` lists one.

When `needsSelection: true`, multiple equally suitable monitor sources exist and the client must pick `sourceId` values explicitly (same pattern as WLAN scan).

---

## 5. Sessions

### 5.1 Create — `POST /api/v1/wifi/capture/sessions`

Creates a session, optionally starts capture immediately.

```json
{
  "mode": "summary",
  "sources": [
    { "sourceId": "root/wlanpi0" }
  ],
  "filter": {
    "frameFilter": "beacons",
    "stripPayload": true,
    "dwellTimeMs": 250,
    "bands": ["UNII-1", "UNII-2A", "UNII-2C", "UNII-3"],
    "channels": []
  },
  "allowDisruptive": false,
  "subscriberAccess": "token",
  "autoStart": true,
  "durationSec": null
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `mode` | `summary` | `summary` \| `stream` \| `file` |
| `sources` | required | One or more `sourceId` from discovery |
| `filter.frameFilter` | `beacons` | `beacons` \| `beacons_and_data` \| `all` |
| `filter.stripPayload` | `true` | Limit snaplen — no L3–7 MSDU (matches UI “Do not save Layer 3–7 payload”) |
| `filter.dwellTimeMs` | `250` | Per-channel dwell for hop sequence |
| `filter.bands` | `[]` | UNII presets; core expands to MHz channel list |
| `filter.channels` | `[]` | Explicit `{ "freq", "width" }` list; overrides `bands` when non-empty |
| `allowDisruptive` | `false` | Must be `true` to use `disrupts_connection` or `requires_mode_change` sources |
| `subscriberAccess` | `token` | `token` (secure default) \| `public` (explicit opt-in — see §7) |
| `autoStart` | `true` | Begin capture on create |
| `durationSec` | null | Auto-stop after N seconds; null = until stop |

**Response (`201`):**

```json
{
  "sessionId": "cap_01HXYZ…",
  "mode": "summary",
  "state": "running",
  "controlToken": "ct_…",
  "subscribeToken": "st_…",
  "subscribeTokenExpiresAt": "2026-06-14T20:30:00+00:00",
  "subscribeUrl": "wss://device/api/v1/streaming/capture?session=cap_01HXYZ…&token=st_…",
  "sources": [
    {
      "sourceId": "root/wlanpi0",
      "iface": "wlanpi0",
      "namespace": "root",
      "state": "running",
      "currentFreq": 5180,
      "currentWidth": 20
    }
  ],
  "subscriberAccess": "token"
}
```

`subscribeUrl` is omitted when `mode=summary` only and `subscriberAccess=token` with no stream consumers — MCP clients use `/frames` only.

### 5.2 Disruptive capture policy

If any selected source has `usable: false`:

| `allowDisruptive` | Result |
|-------------------|--------|
| `false` (default) | **409** `CAPTURE_SOURCE_NOT_USABLE` with `alternatives` |
| `true` | Allowed; response includes `"disruptive": true` and audit log entry |

Core **never** implicitly creates monitor interfaces or deactivates namespace configs. Destructive PHY/mode changes require separate explicit APIs (P1).

### 5.3 Control lease

- One **control holder** per session (the creator, unless transferred).
- `PATCH`, `POST .../stop` require header `X-Capture-Control-Token: {controlToken}` (or Bearer scope).
- Second controller without lease: **409** `CONTROL_HELD`.
- Takeover only with `force: true` on PATCH (explicit).

Subscribers **cannot** obtain control via subscribe token.

### 5.4 Status — `GET /api/v1/wifi/capture/sessions/{id}`

```json
{
  "sessionId": "cap_01HXYZ…",
  "mode": "summary",
  "state": "running",
  "startedAt": "2026-06-14T20:00:00+00:00",
  "frameCount": 1247,
  "sources": [ … ],
  "subscriberAccess": "token",
  "subscriberCount": 2
}
```

### 5.5 Update — `PATCH /api/v1/wifi/capture/sessions/{id}`

Requires control token. Mid-session updates:

- `filter.dwellTimeMs`, `filter.channels`, `filter.bands`, `filter.frameFilter`
- Add/remove sources (may restart per-source `dumpcap`)

Core applies changes per source in the correct namespace. Channel hop loops restart with new dwell/channels.

### 5.6 Stop — `POST /api/v1/wifi/capture/sessions/{id}/stop`

Requires control token. Idempotent.

### 5.7 Summary frames — `GET /api/v1/wifi/capture/sessions/{id}/frames`

**Primary MCP data path.**

| Query | Default | Description |
|-------|---------|-------------|
| `limit` | `100` | Max frames (cap e.g. 500) |
| `since` | — | ISO timestamp or monotonic sequence cursor |
| `type` | — | Filter: `beacon`, `data`, `mgmt`, … |

```json
{
  "frames": [
    {
      "seq": 12001,
      "ts": "2026-06-14T20:01:02.345Z",
      "sourceId": "root/wlanpi0",
      "iface": "wlanpi0",
      "freq": 5180,
      "channel": 36,
      "rssi": -62,
      "frameType": "beacon",
      "bssid": "aa:bb:cc:dd:ee:01",
      "ssid": "Example",
      "length": 312
    }
  ],
  "nextSince": "12001"
}
```

Auth: JWT/HMAC, or **read token** (`X-Capture-Subscribe-Token`) for delegated read access.

### 5.8 Files — `GET /api/v1/wifi/capture/sessions/{id}/files`

When `mode` includes file sink — list output paths and sizes.

---

## 6. Filtering (UI mapping)

| UI control | API field | Core behaviour |
|------------|-----------|----------------|
| Beacons only | `frameFilter: "beacons"` | BPF: management beacon subtypes |
| Include data frames | `frameFilter: "beacons_and_data"` | Beacon + data frames |
| Do not save L3–7 payload | `stripPayload: true` | Reduced snaplen (802.11 + radiotap; no MSDU) |
| Channel dwell (ms) | `dwellTimeMs` | Per-channel sleep in hop loop |
| UNII-1 / 2A / 2C / 3 / 5 … | `bands[]` | Core expands to `{freq, width}` list |

BPF is compiled **server-side** from structured filter — clients do not send raw BPF strings in P0.

---

## 7. Subscriber access and security

**Secure by default.**

| `subscriberAccess` | Behaviour |
|--------------------|-----------|
| `token` (default) | `subscribeToken` required on WebSocket and on `/frames` read |
| `public` | Explicit opt-in at session create; stream and frames readable **without** token until session ends |

Making a session public requires **`subscriberAccess: "public"`** in create body. There is no implicit public access.

| Role | Credentials |
|------|-------------|
| Controller | Device JWT/HMAC + `controlToken` |
| Subscriber | `subscribeToken` (scoped read-only, TTL, revocable) |
| Public subscriber | Only when session created with `subscriberAccess: "public"` |

Control commands on WebSocket (`start`, `stop`, `configure`) are **rejected** for subscribe tokens — control is REST-only in P0.

---

## 8. WebSocket stream (`mode: stream`)

Extends existing `WS /api/v1/streaming/capture`:

```
wss://host/api/v1/streaming/capture?session={sessionId}&token={subscribeToken}
```

| Message | Direction | Content |
|---------|-----------|---------|
| Binary frames | Server → client | pcapng bytes (multi-interface multiplexed) |
| Text events | Server → client | JSON: `CHANNEL_SET`, `CAPTURE_STARTED`, errors |

**Channel attribution:** clients parse **Radiotap** `channel.freq` / `channel.flags` per packet. JSON `CHANNEL_SET` events are advisory for UI sync during hops.

Legacy direct-WS clients (no session) remain supported during migration but are deprecated.

---

## 9. Multi-source and namespaces

- Each `sourceId` runs capture inside **`ns_exec`** for its namespace.
- **Single session** may include multiple sources (multiple namespaces).
- **Stream:** one pcapng multiplex; demux via pcapng interface ID + radiotap + `sourceId` in summary mode.
- **Independent hop loops** per source with per-source `filter` override (P1; shared filter in P0).

Time alignment: pcapng timestamps are authoritative; receivers join on `{ts, sourceId}`.

---

## 10. MCP tool mapping (P0)

| MCP tool | REST |
|----------|------|
| `wlan_capture_list_sources` | `GET /wifi/capture/sources` |
| `wlan_capture_start` | `POST /wifi/capture/sessions` with `mode: "summary"` |
| `wlan_capture_frames` | `GET /wifi/capture/sessions/{id}/frames` |
| `wlan_capture_status` | `GET /wifi/capture/sessions/{id}` |
| `wlan_capture_stop` | `POST /wifi/capture/sessions/{id}/stop` |

MCP **does not** open WebSocket in P0. Stream mode is for non-MCP application developers.

---

## 11. Error codes

| HTTP | Code | When |
|------|------|------|
| 409 | `CAPTURE_SOURCE_NOT_USABLE` | Source not usable and `allowDisruptive` false |
| 409 | `CONTROL_HELD` | Another controller holds the lease |
| 404 | `SESSION_NOT_FOUND` | Unknown session id |
| 401 | `SUBSCRIBE_TOKEN_REQUIRED` | Missing/invalid subscribe token |
| 403 | `CONTROL_TOKEN_REQUIRED` | PATCH/stop without control token |
| 422 | `NO_CAPTURE_SOURCE` | No suitable sources on device |

---

## 12. Implementation phases

| Phase | Deliverable |
|-------|-------------|
| **P0a** | `GET /wifi/capture/sources`, session CRUD, summary `/frames`, auth tokens |
| **P0b** | WS session bridge, multi-source same-namespace |
| **P0c** | Multi-namespace sources, `subscriberAccess: public` |
| **P1** | Per-source filter, monitor create/promote API, file mode |
| **P1** | Deprecate unauthenticated legacy WS |

---

## 13. Changelog

| Date | Change |
|------|--------|
| 2026-06-14 | Initial design: session hub, sources discovery, summary-first MCP, secure-by-default subscribers |
