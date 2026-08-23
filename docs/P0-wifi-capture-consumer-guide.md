# WiFi packet capture — application developer guide

**Status:** Design (P0 — implementation pending)  
**Audience:** Mobile apps, scanner tools, MCP servers, automation, wlanpi-ui job runner authors

**Core design (implementers):** [P0-wifi-capture-api.md](./P0-wifi-capture-api.md)  
**Related:** [WLAN scan API](./P0-utils-wlan-scan-api.md) (one-shot scan, not live capture)

---

## 1. What you are building

There are three roles. Pick the one that matches your app:

| Role | Your job | APIs you use |
|------|----------|--------------|
| **Controller** | Start/stop capture, set channels and filters | REST + control token |
| **Subscriber** | Read live pcap or summary frames someone else started | WebSocket and/or `/frames` + subscribe token |
| **MCP / AI agent** | Decide capture is needed, inspect packets, stop | REST only, **`summary` mode** |

You do **not** need to understand network namespaces. Core exposes a flat **`sources`** list with clear **usable / risk** flags.

---

## 2. Quick start (controller, summary mode)

Typical flow for an app or AI tool:

```
1. GET  /api/v1/wifi/capture/sources
2. Pick source(s) where usable === true
3. POST /api/v1/wifi/capture/sessions   (mode: "summary")
4. Poll GET .../sessions/{id}/frames
5. POST .../sessions/{id}/stop
```

### 2.1 List sources

```http
GET /api/v1/wifi/capture/sources
Authorization: Bearer …
```

Pick entries with `"usable": true`. Prefer monitor interfaces (`"mode": "monitor"`, `"captureReady": true`).

If the source you want has `"usable": false`, read `"alternatives"` — often a monitor sibling exists (e.g. use `wlanpi0` instead of connected `wlan0`).

### 2.2 Start capture

```http
POST /api/v1/wifi/capture/sessions
Authorization: Bearer …
Content-Type: application/json

{
  "mode": "summary",
  "sources": [{ "sourceId": "root/wlanpi0" }],
  "filter": {
    "frameFilter": "beacons",
    "stripPayload": true,
    "dwellTimeMs": 250,
    "bands": ["UNII-1", "UNII-2A", "UNII-2C", "UNII-3"]
  },
  "allowDisruptive": false,
  "subscriberAccess": "token",
  "autoStart": true
}
```

Save from the response:

- `sessionId`
- `controlToken` — required for stop/PATCH
- `subscribeToken` — pass to subscribers (if any)

### 2.3 Read frames (summary)

```http
GET /api/v1/wifi/capture/sessions/{sessionId}/frames?limit=100&since=12001
Authorization: Bearer …
```

Use `nextSince` from the response for incremental polling.

### 2.4 Stop

```http
POST /api/v1/wifi/capture/sessions/{sessionId}/stop
X-Capture-Control-Token: {controlToken}
```

---

## 3. Quick start (subscriber)

A **controller** app started the session and shared a **subscribe token** with you.

### 3.1 Summary subscriber (read parsed frames)

```http
GET /api/v1/wifi/capture/sessions/{sessionId}/frames?limit=50
X-Capture-Subscribe-Token: {subscribeToken}
```

No device JWT required if the token is valid and the session is running.

### 3.2 Stream subscriber (live pcap)

Connect to the URL from the create response:

```
wss://{host}/api/v1/streaming/capture?session={sessionId}&token={subscribeToken}
```

- **Binary messages:** pcapng data — feed to your parser or save to file
- **Text messages:** JSON events (`CHANNEL_SET`, status, errors)

You **cannot** send `start` / `stop` / `configure` on this connection — read-only.

---

## 4. Discovery without namespaces

Use **`sourceId`** everywhere (e.g. `"root/wlanpi0"`, `"scan_ns/wlanpi1"`). The namespace is embedded for core routing; your UI can show `label` only.

| Field | What to show users |
|-------|-------------------|
| `label` | Human-readable one-liner |
| `usable` | Enable “Start capture” only when `true` |
| `risk` | Show warning if not `none` |
| `connected` + `connectedSsid` | “Connected to … — capture would disconnect” |
| `alternatives` | Action buttons: “Use wlanpi0 instead” |

### 4.1 Connected Wi‑Fi and why capture is blocked

If **`wlan0` is connected** to an access point, it is in **managed** mode with an active link. Packet capture with channel hopping on that interface **would drop the connection**.

Core marks such interfaces:

```json
{
  "usable": false,
  "risk": "disrupts_connection",
  "connected": true,
  "connectedSsid": "OfficeWiFi"
}
```

**What your app should do:**

1. Do **not** offer one-tap capture on that source.
2. Offer the **`alternatives`** entry (usually a monitor interface on the same radio).
3. Only if the user explicitly confirms disruption, retry with `"allowDisruptive": true`.

You never need to ask “should we disrupt?” unless the user deliberately chose a blocked source — default UX is safe.

---

## 5. Filter settings (match the capture UI)

| User setting | JSON |
|--------------|------|
| Beacons only | `"frameFilter": "beacons"` |
| Include data frames | `"frameFilter": "beacons_and_data"` |
| Do not save L3–7 payload | `"stripPayload": true` |
| Channel dwell 250 ms | `"dwellTimeMs": 250` |
| UNII band checkboxes | `"bands": ["UNII-1", "UNII-2A", …]` |

Do not build BPF strings client-side — send structured `filter` and let core compile it.

---

## 6. Channel attribution

Each frame in **summary mode** includes `freq` and `channel` (derived from Radiotap).

In **stream mode**, parse Radiotap in each pcap record — that is the ground truth for which channel was heard. JSON `CHANNEL_SET` events on the WebSocket are for UI indicators during hops, not a substitute for per-packet Radiotap.

---

## 7. Authentication cheat sheet

| Action | Auth |
|--------|------|
| List sources | Device JWT or localhost HMAC |
| Create session | Device JWT or HMAC |
| Stop / PATCH session | `X-Capture-Control-Token` |
| Read frames (controller) | Device JWT or HMAC |
| Read frames (subscriber) | `X-Capture-Subscribe-Token` |
| WebSocket stream | `token` query param |

### 7.1 Secure by default

- **`subscriberAccess: "token"`** (default) — subscribers need the token the controller received at create time.
- **`subscriberAccess: "public"`** — only if the controller **explicitly** opts in at session create. Use for lab/demo scenarios where handing out a token is impractical. **Not the default.**

There is no global “open capture stream” — public access is per-session and explicit.

### 7.2 One controller, many subscribers

- Only **one app** should hold the **control token** (start/stop/channels).
- Any number of apps may subscribe with the **subscribe token** (read-only).
- If another app tries to take control: **409** `CONTROL_HELD` — use `force: true` only with explicit user confirmation.

---

## 8. MCP / AI integration

P0 MCP tools use **summary mode only** — no WebSocket.

Recommended agent loop:

```
list_sources → choose usable monitor source
→ start(session, mode=summary, frameFilter=beacons)
→ loop: frames(limit=100) until enough data or timeout
→ stop(session)
```

Example frame for model reasoning:

```json
{
  "frameType": "beacon",
  "ssid": "CorpGuest",
  "bssid": "aa:bb:cc:dd:ee:01",
  "channel": 36,
  "freq": 5180,
  "rssi": -58
}
```

OpenAPI + MCP tool names are listed in [P0-wifi-capture-api.md §10](./P0-wifi-capture-api.md#10-mcp-tool-mapping-p0).

---

## 9. TypeScript types (illustrative)

```typescript
type CaptureSource = {
  sourceId: string;
  iface: string;
  namespace: string;
  label: string;
  mode: "monitor" | "managed";
  captureReady: boolean;
  usable: boolean;
  risk: "none" | "disrupts_connection" | "requires_mode_change" | "namespace_busy";
  connected: boolean;
  connectedSsid?: string | null;
  alternatives: Array<{
    action: string;
    sourceId?: string;
    label?: string;
  }>;
};

type CaptureFilter = {
  frameFilter?: "beacons" | "beacons_and_data" | "all";
  stripPayload?: boolean;
  dwellTimeMs?: number;
  bands?: string[];
  channels?: Array<{ freq: number; width: number }>;
};

type CreateSessionBody = {
  mode?: "summary" | "stream" | "file";
  sources: Array<{ sourceId: string }>;
  filter?: CaptureFilter;
  allowDisruptive?: boolean;
  subscriberAccess?: "token" | "public";
  autoStart?: boolean;
  durationSec?: number | null;
};
```

---

## 10. Error handling

| Situation | HTTP | Your UX |
|-----------|------|---------|
| Picked connected `wlan0` | 409 `CAPTURE_SOURCE_NOT_USABLE` | Show alternatives; offer monitor sibling |
| Another app controlling | 409 `CONTROL_HELD` | “Capture in use by another app” |
| Invalid subscribe token | 401 | Re-request token from controller |
| Session ended | 404 | Stop polling; prompt restart |

Always call **`GET /wifi/capture/sources`** before start — do not cache interface names across namespace config changes.

---

## 11. Relationship to WLAN scan

| Need | API |
|------|-----|
| One-time AP list (picker, site survey snapshot) | `GET /api/v1/utils/wlan/scan` |
| Live beacons / continuous RF / pcap | Capture session (this guide) |

Do not poll scan every few seconds for “live” data — use capture summary or stream.

---

## 12. Implementation status

This guide describes the **target P0 API**. Until endpoints ship, legacy `WS /api/v1/streaming/capture` exists without sessions, auth, or summary mode. Check [gap matrix](./p0-api-gap-matrix.csv) for `Live` status.

When implementation lands, bind capabilities:

| Capability | Endpoint |
|------------|----------|
| `wifi.capture.sources` | `GET /wifi/capture/sources` |
| `wifi.capture.start` | `POST /wifi/capture/sessions` |
| `wifi.capture.status` | `GET /wifi/capture/sessions/{id}` |
| `wifi.capture.stop` | `POST /wifi/capture/sessions/{id}/stop` |
| `wifi.capture.frames` | `GET /wifi/capture/sessions/{id}/frames` |

---

## 13. Changelog

| Date | Change |
|------|--------|
| 2026-06-14 | Initial consumer guide aligned with core design doc |
