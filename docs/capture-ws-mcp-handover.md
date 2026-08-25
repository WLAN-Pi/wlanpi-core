# Handover: WiFi packet capture over the core WebSocket → wlanpi-mcp

**Audience:** whoever adds packet-capture tools to wlanpi-mcp (and the coding
agents they drive). **Prereq reading:** the auth plan (`docs/mcp-auth-plan.md`)
and its Appendix A. **Reference client:** `tools/capture_harness/` in this repo
implements everything below and is worth reading as a worked example.

This describes a **finished, tested** core capability and how MCP should consume
it. The core side is done on branch `feature/capture-auth`; nothing here asks
for core changes.

---

## 1. What core provides

A single WebSocket endpoint:

```
ws://<host>:31415/api/v1/streaming/capture      (plain, current)
wss://<host>:.../api/v1/streaming/capture       (TLS - see §6, not yet through nginx)
```

It authenticates per-connection, runs one owned capture per socket, streams
**pcapng** binary frames, and lets other authenticated connections **subscribe
read-only** to a running capture. There is no REST capture API; this WebSocket
is the interface.

### Message protocol

All client→server messages are JSON text. The **first** message MUST be auth:

```json
{"command": "auth", "token": "<core JWT>"}
```

Server replies `AUTH_OK` (or closes with code **4401** on failure / a 10s
timeout / a token in the URL). After that:

| Command | Payload | Notes |
|---|---|---|
| `get_supported_frequencies` | `{}` | channel list the device supports |
| `configure` | `{"interfaces": {"wlanpi0": {"channels": [{"freq": 2412, "width": 20}], "dwell_time": 250}}}` | per-interface config; `width` ∈ {20,40,80,160}, `dwell_time` 50–60000 ms |
| `start` | `{"interfaces": ["wlanpi0"], "pcap_filter": ""}` | begins capture; interfaces must be configured first |
| `stop` | `{}` | owner only |
| `subscribe` | `{"session_id": "cap_xxxx"}` | listen read-only to another socket's capture |
| `unsubscribe` | `{}` | detach |
| `list_sessions` | `{}` | enumerate running captures |

Interface names must match `wlanpiN` (the monitor-mode interface), not `wlan0`.

### Server→client messages

- **Binary frames** = pcapng bytes (multiplexed if multiple interfaces). These
  arrive in unaligned chunks; buffer and parse pcapng blocks incrementally.
- **Text events** = `{"type","event","code","data"}`. Key codes:
  `AUTH_OK` (`data.did`), `CAPTURE_STARTED` (`data.session_id`,
  `data.interfaces`), `CHANNEL_SET` / `CHANNEL_SET_FAILED` (hop status; failure
  `data.message` carries the `iw` reason), `SUBSCRIBED`, `SESSIONS`
  (`data.sessions`), `CAPTURE_STOPPED` / `CAPTURE_ENDED`, and `error` events
  (`AUTH_FAILED`, `INTERFACE_IN_USE`, `SESSION_NOT_FOUND`, `CONFIG_INVALID`, …).

---

## 2. Identity and ownership model (read this before designing tools)

- The connection's principal is the **`did`** from the verified JWT. Core binds
  each running capture to the owning socket; only that socket can
  `configure`/`stop` it. Any *other* authenticated connection may `subscribe`
  read-only (device-open reads — see Appendix A policy A).
- **The capture lives with its owning socket.** If the socket closes, the
  capture stops and subscribers are detached. There is no detached/durable
  capture that outlives its connection.
- **Revocation** stops new connections and new captures immediately, but does
  **not** tear down a socket that is already streaming (documented Prague
  semantic; see Appendix A decision 3).

Implication for MCP: a capture is only alive while MCP holds the WebSocket. Map
this to explicit tool-invocation lifetime, not a background daemon that
outlives a request — and never a protocol session id used as an auth cookie
(the auth plan §2.2 forbids that). If MCP needs "start now, read later", MCP
itself must hold the socket open and expose a handle; do not expect core to
keep an ownerless capture.

---

## 3. How MCP should consume this (two viable shapes)

### Shape A — MCP as the capture owner (recommended for summary tools)

MCP opens the WebSocket, authenticates, `configure` + `start`, reads binary
frames for a bounded window, dissects them, and returns a **summary** (AP list,
frame counts, a specific frame decode). This fits the MCP tool model: a tool
call does bounded work and returns structured data. `tools/capture_harness/`
`run_owner` is exactly this flow.

Good tools to expose:
- `capture_scan(interface, channels, dwell_ms, duration_s)` → list of APs
  (SSID, BSSID, channel, signal, security, PHY, tx power). The harness's
  `parse_beacon` + `ScanTable` is a drop-in reference for the dissection.
- `capture_frames(interface, channels, duration_s, pcap_filter)` → decoded
  frame summaries or counts by type.
- `list_capture_sources()` → wrap `get_supported_frequencies`.

Do **not** stream raw pcap to the LLM; summarize. Return small JSON.

### Shape B — MCP as a subscriber

If another app (WebUI, a lab controller) owns a capture, MCP can `subscribe`
with `data.session_id` from `list_sessions` and consume the same stream
read-only. Use this for "observe the capture the instructor started". MCP still
authenticates as itself; it does not need to be the owner.

---

## 4. Auth: where MCP's token comes from (do NOT hardcode)

MCP forwards a wlanpi-core JWT as the WebSocket's first-message token. Per the
auth plan:

- The user's JWT is issued by core (`getjwt` for Prague; env/keychain on the
  client, never pasted into `mcp.json`). MCP reads it the same way it reads the
  token for its REST calls today.
- After core issue #139 (credential-based dispatch, on branch
  `feature/credential-auth-dispatch`), MCP presents a plain Bearer to core over
  localhost with no `X-Wlanpi-Client` header. The capture WebSocket is on the
  same core; use the same token.
- Send the token **in the first WebSocket message only**. Never put it in the
  URL query string — core refuses `?token=` (it would be logged) and closes
  4401.

The plan's longer-term "MCP validates its own audience, uses a service identity
to core" direction (§2.2) applies to capture too, but for Prague the capture
tools use the same user JWT flow as the rest of MCP.

---

## 5. Implementation checklist for the MCP capture module

1. WebSocket client (the `websockets` library works; the harness uses it).
2. Authenticate first; handle 4401 / `AUTH_FAILED` as a clean tool error.
3. `configure` then `start`; capture the `session_id` from `CAPTURE_STARTED`.
4. Incremental pcapng reader (chunks are unaligned; a new SHB can appear
   mid-stream — reset interface state on it). See `PcapngReader` in the harness.
5. Bounded read: stop after `duration_s` or a frame budget; always `stop` and
   close in a `finally`.
6. Dissect to a compact summary. Reuse the harness's radiotap + IE parsing
   scope (SSID, channel, signal, security, HT/VHT/HE/EHT, tx power) or extend
   it; do not ship raw pcap to the model.
7. Surface `CHANNEL_SET_FAILED` reasons in the tool result — on single-radio
   devices hopping can fail while the managed interface scans (see §7).
8. Subscriber tool: `subscribe` with a `session_id` from `list_sessions`;
   otherwise identical consumption.
9. Never keep an ownerless background capture; tie capture lifetime to the tool
   invocation (or to MCP explicitly holding the socket for a handle it owns).

---

## 6. TLS / transport

Today the capture WebSocket is reachable on the plain core port `:31415`
(loopback for on-box MCP). The P3 nginx TLS front-ends terminate HTTPS for the
REST API and MCP but **do not yet forward the WebSocket `Upgrade`/`Connection`
headers**, so `wss://` through nginx is not available until that is added
(tracked as capture-TLS follow-up). On-box MCP calling core over loopback does
not need TLS; a remote MCP consumer does, and that is gated on the nginx
WebSocket-proxy change. Do not design around `wss://` through nginx yet.

---

## 7. Hardware reality: single-radio channel hopping

On devices where the capture interface shares one phy with the managed `wlan0`
(e.g. the Pi's onboard adapter), retuning the monitor interface fails with
`Device or resource busy (-16)` while `wlan0` is scanning. Core retries a busy
channel-set once; a persistent failure emits `CHANNEL_SET_FAILED` with the
reason. For reliable multi-channel capture the device needs the managed
interface down or a second adapter (its own phy). MCP tool docs should tell the
user this rather than presenting a silent partial capture as complete.

---

## 8. Open questions to confirm with the core owner before shipping

- Subscriber policy: Prague ships device-open reads (any valid token may
  listen). If MCP needs per-stream ACLs, that is a core policy change
  (Appendix A) — raise it, don't assume it.
- Revocation vs live sockets: if a captured/leaked token must immediately kill
  an in-flight MCP capture stream, that is a core change (Appendix A decision
  3), currently "beyond Prague".
- Durable/detached captures (start now, collect later without holding the
  socket): not supported today; needs the REST session design, out of Prague
  scope.
