# MCP classroom labs — instructor notes

**Read first:** [MCP-CLASSROOM-LABS.md](./MCP-CLASSROOM-LABS.md) — lab design, expected agent routes, rubrics.
**Hand to students:** [MCP-LAB-GUIDE.md](./MCP-LAB-GUIDE.md) — worksheet only. It contains no answers.

This file covers building the room, staging each fault, running the day, and recovering when it goes wrong.

---

## 1. Decide your running mode first

Everything else follows from this. The capture REST API is **design-stage** — it is not in `docs/openapi.json` yet.

| Mode | You need | Labs available | Prep |
|------|----------|----------------|------|
| **H** Hardware full | Capture REST shipped | All | 3 h first time |
| **M** Hardware + mock capture | Live Pis + the mock in §6 | All | 3 h + 30 min for the mock |
| **L** Hardware lite | Live Pis only | L01–L10, reduced L13 | 2 h |
| **T** Tabletop | Nothing | All, as reasoning drills | 1 h printing |

**Run Mode M unless capture REST has shipped.** In Mode M the agent sees the designed API shape and behaves identically; only the frame data is canned. Students cannot tell, and Tier 2's lesson — choosing a non-disruptive source — survives intact.

**If you must run Mode L:** drop L11 and L12 rather than degrade them into "scan twice", which teaches the opposite of the intended lesson. Substitute side labs S2 and S3 from the plan's §7.6.

> **Say this to the class at the start of Tier 2 in Mode M:** "The capture API is served by a stand-in today. The shape is the real design; the frames are recorded. Everything you learn about choosing a safe source is real." Do not let students discover it themselves — it damages trust in the rest of the day.

---

## 2. Kit

### 2.1 Per pair

| Item | Notes |
|------|-------|
| 1 × WLAN Pi | Classic mode. Pro/R4 fine. **One per pair, not per student** — the pairing drives the discussion |
| Ethernet to the lab switch | Management path. This must stay up all day |
| Laptop with an MCP client | Claude Code or equivalent, configured against the pair's Pi |
| Sealed envelope | Lab SSID + PSK. **Sealed** — issue at L06, not before |
| Printed lab guide | Paper works better than a second window |

Optional but strongly recommended: **one USB Wi-Fi adapter per pair** for L05. Without a second monitor-capable radio, `needsSelection` never fires and L05 loses its trap. If you have only a few, run L05 as a rotation.

### 2.2 Room infrastructure

| Role | SSID | Config | Used by |
|------|------|--------|---------|
| Lab join target | `WLANPI-LAB` | WPA2-PSK, 5 GHz UNII-1 (ch 36), known PSK | L06–L08, L12, L14 |
| Congested | `WLANPI-GUEST` | 2.4 GHz **ch 6**, 20 MHz, open or simple PSK | L08, L13, L14 |
| Hidden | *(SSID broadcast off)* | Any band, steady beacon | L11, L14 |
| Rogue twin | `WLANPI-LAB` | **2.4 GHz**, open or different PSK, weaker | L12, L14 |
| Enterprise bait | `CorpSecure` | WPA2-Enterprise (PEAP), no student certs | L06, L14 |
| DFS | `WLANPI-DFS` | UNII-2C, if your reg domain permits | S2 |

Five SSIDs need not be five APs. Most APs will run 3–4 SSIDs per radio. A practical minimum:

- **AP1** (dual-band): `WLANPI-LAB` on 5 GHz + `CorpSecure` on 5 GHz + `WLANPI-GUEST` on 2.4 GHz
- **AP2** (cheap, 2.4 only): rogue `WLANPI-LAB` + hidden SSID

Two consumer APs or a spare Pi running `hostapd` will do it.

### 2.3 Congestion generator for channel 6

`WLANPI-GUEST` must genuinely look bad, or L08 and L13 have no evidence to find. Any of:

- A laptop on guest streaming video on loop (simplest, most realistic)
- `iperf3` UDP between two clients on guest, rate-limited to ~20 Mbit
- 2–3 spare APs beaconing on ch 6 with no clients (raises neighbour count but **not** BSS load — pair with one of the above)

**Verify before class.** From a Pi, `GET /api/v1/utils/wlan/scan?detail=full` and confirm the guest BSS reports a `bssLoad` with non-trivial `utilization`. If `bssLoad` is absent, your AP is not advertising the BSS Load IE — enable it (often "WMM"/"airtime fairness" related) or L08's evidence disappears and you must fall back to neighbour count and RSSI.

---

## 3. Staging each fault

Run these on the pair's Pi unless stated. Each has a verification step — **use it**, a fault that silently did not apply wastes 20 minutes of class time.

### L02 — Break name resolution

Point the resolver at a black hole while leaving the gateway reachable.

```bash
resolvectl dns eth0 192.0.2.53 && resolvectl flush-caches
```

**Verify:** `GET /api/v1/utils/reachability` → `Ping Gateway` shows an RTT, `DNS Server 1 Resolution` and `Browse Google` show `FAIL`.
**Revert:** `resolvectl revert eth0`

If `systemd-resolved` is not managing the link, edit the DHCP-supplied resolver or add a bogus `nameserver` at the top of the resolver config instead. Whatever you do, **the gateway must still ping** — that contrast is the lab.

### L04 — Force a bad Ethernet negotiation

On the **switch**, set the pair's port to 100 Mb half-duplex. If the switch is unmanaged, do it from the Pi:

```bash
ethtool -s eth0 speed 100 duplex half autoneg off
```

**Verify:** `GET /api/v1/network/interfaces/eth0/link-stats` reports 100 Mb / half.
**Revert:** `ethtool -s eth0 autoneg on`

> Do this **after** the Pi is on the network and confirm the management path survives. Half duplex is slow, not broken — if the link drops entirely, revert and skip the twist.

### L05 — Two monitor radios

Insert the USB adapter and make sure both it and the on-board radio are monitor-capable and visible.

**Verify:** `GET /api/v1/utils/wlan/scan` (no params) returns `200` with `needsSelection: true`, `candidates[]` populated, and **`networks[]` empty**. If it returns networks, only one radio qualified — the lab's trap will not fire.

### L06 — Enterprise bait

`CorpSecure` must be genuinely joinable-looking and genuinely unjoinable. WPA2-Enterprise PEAP with a RADIUS server the students have no account on, or a RADIUS that rejects everything. It must appear in scan output with EAP in its `flags`.

**Verify:** the `CorpSecure` row in a scan shows `key_mgmt` / `flags` indicating EAP, not `wpa-psk`.

### L07 — Pick exactly one fault

Choose per pair and **write down which** — you will need it for the debrief.

| Variant | How to stage | Verify |
|---------|--------------|--------|
| **(a) No lease** | Release the WLAN interface's lease, or block DHCP for its MAC on the server | `GET /network/interfaces` shows no IPv4 on the WLAN iface |
| **(b) Dead resolver** | As L02, but on the WLAN interface | Association fine, DNS `FAIL` |
| **(c) Route on Ethernet** | Set `default_route: false` on the WLAN NetConfig, leave Ethernet's default in place | `GET /network/routing` shows the default via `eth0` |

Variant **(c)** produces the most interesting debrief: nothing is actually broken, and a careless agent reports an outage.

### L11 — Hidden AP

Disable SSID broadcast on AP2's second SSID. The beacon must still transmit — that is the whole point.

**Verify:** `GET /api/v1/utils/wlan/scan?hidden=false` omits it; `GET /api/v1/utils/wlan/scan` (default `hidden=true`) shows a row with an empty `ssid` and a real BSSID.

### L12 / L14 — Rogue twin

AP2 broadcasts `WLANPI-LAB` on 2.4 GHz, **open or with a different PSK**, and positioned so it is clearly weaker than the genuine 5 GHz one.

**Verify:** one scan shows two rows with SSID `WLANPI-LAB` and different BSSIDs, bands and `key_mgmt`.

> Tempting mistake: making the rogue *stronger* to be "more realistic". Don't — for L12, the weaker rogue is what makes the signal-strength trap fire.

### L14 — Clock skew (the capstone twist)

```bash
timedatectl set-ntp false && timedatectl set-time "2019-03-04 09:00:00"
```

**Verify:** `GET /api/v1/system/datetime` reports the skewed date.
**Revert:** `timedatectl set-ntp true`

This is the highest-value fault in the pack: certificate validation fails because of the clock, which looks like an RF or credential problem and is neither. Very few agents connect it unprompted — that is why it is a bonus, not a requirement.

> **Do this last, immediately before the capstone.** A skewed clock breaks TLS to package repos, LibreSpeed and possibly your MCP client's own auth. Never leave it set during Tiers 0–3.

### L14 — Guest fault

Pick **one** and do not tell the students which:
- Rate-limit the guest SSID's WAN to ~2 Mbit (most APs do this natively), or
- Break the guest DHCP scope's DNS option

### S1 — Hotspot lab

Requires flipping a Pi to hotspot mode. Do this on **one demo Pi**, not the class set, and do it at the end — NetConfig activate stops working in hotspot mode and every earlier lab depends on it.

---

## 4. Pre-flight checklist

Run this 30 minutes before class, per pair. It takes about 4 minutes each and it will save the session.

```bash
# Substitute the pair's Pi hostname
H=wlanpi-01.local; P=8000
curl -s http://$H:$P/api/v1/system/device/info            # mode == classic
curl -s http://$H:$P/api/v1/utils/reachability            # gateway + DNS OK
curl -s "http://$H:$P/api/v1/utils/wlan/scan?detail=full" # all kit SSIDs present
curl -s http://$H:$P/api/v1/network/config/status         # no stale active config
curl -s http://$H:$P/api/v1/utils/blinker/status          # not left running
curl -s http://$H:$P/api/v1/system/datetime               # clock correct
```

| Check | Must be |
|-------|---------|
| Device mode | `classic` |
| Clock | Correct (skew it only for L14) |
| Kit SSIDs visible | `WLANPI-LAB` ×2, `WLANPI-GUEST`, `CorpSecure`, hidden row |
| Guest BSS load | Present and non-trivial |
| Active NetConfig | None left from a previous run |
| Blinker | Stopped |
| Capture sessions | None (Mode H/M) |
| MCP client | Authenticates and can call `device_info` |

**Also check your own auth path.** Remote MCP clients receive a JWT from a device-local pairing flow; they do not bootstrap anonymously over the network. On-device services use localhost HMAC. Auth is dispatched on the credentials presented, so confirm your students' clients hold a working bearer *before* the room fills up — a class-wide 401 at L01 is a bad start.

---

## 5. Running the day

### 5.1 Timing

| Block | Labs | Time |
|-------|------|------|
| Intro + safety envelope | — | 15 min |
| Tier 0 | L01–L04 | 40 min |
| Tier 1 | L05–L08 | 70 min |
| *Break* | | 15 min |
| Tier 2 | L09–L10 | 40 min |
| Tier 3 | L11–L12 | 40 min |
| *Break* | | 10 min |
| L13 + debrief | | 45 min |
| L14 capstone | | 55 min |
| Capstone debrief | | 20 min |

Add 25% on a first delivery. If you are running late, **cut Tier 3, not the capstone debrief** — the debrief is where the learning consolidates.

### 5.2 What to do while they work

Circulate and read transcripts, not answers. You are looking for:

| Watch for | Intervention |
|-----------|--------------|
| Agent produced networks after `needsSelection` | Say nothing. Let them submit it. Ask in the debrief: *"which call returned that list?"* |
| Student typing endpoint names into the prompt | Interrupt immediately — it defeats the exercise |
| Agent about to use `allowDisruptive` | Let it happen if the Pi is expendable. The lost connection teaches more than the warning |
| Pair finished 10 minutes early | Give them a side lab (plan §7.6), not the next tier |
| Pair stuck > 10 min on the same call | Ask *"what did the last response actually tell you?"* — usually they have not read it |

### 5.3 Facilitation principles

**Grade the route, not the conclusion.** A wrong congestion story with a stopped capture, a monitor sibling and a cited BSS load number is a better result than a correct guess from one scan. Say this out loud at the start and mean it when marking.

**Never rescue a failing agent.** The recovery is the competency being taught. An agent that hits `409 CAPTURE_SOURCE_NOT_USABLE` and recovers from the `alternatives` array has demonstrated more than one that never made the mistake.

**Make the pairs disagree.** In L08, half the room is on clean 5 GHz and half on congested channel 6. Same prompt, opposite conclusions. Put two answers on the board before explaining why.

**Protect the "I can't tell" answer.** In L12, an agent that says *"I cannot prove which is legitimate from RF alone, but this one matches your issued credentials"* is giving the best available answer. Reward calibration explicitly or the class learns to reward confidence.

### 5.4 Debrief structure

Twenty minutes, in this order:

1. **Two transcripts on the projector** — one strong, one that fell into the trap. Anonymised. Ask the room to spot the divergence point before you name it.
2. **The failure taxonomy** (plan §8) as rapid-fire questions. Ask them even of pairs that did not commit the error.
3. **The time comparison.** Collect their honest hand-estimates from L13's think box. Put the range on the board next to the agent's actual elapsed time.
4. **The unsupervised question.** *"Would you let this run against a production network? Where is your line?"* This is the discussion the day exists for. Do not rush it, and do not resolve it for them.

---

## 6. Mode M — the capture mock

A small stand-in serving the five designed capture endpoints, so Tiers 2–4 run before capture REST ships. It mirrors the shapes in [P0-wifi-capture-api.md](./P0-wifi-capture-api.md) and the [consumer guide](./P0-wifi-capture-consumer-guide.md).

Run it on the instructor laptop or the Pi, on a separate port, and point students' MCP capture tools at it. Everything else stays on the real Pi.

```python
# capture_mock.py — Mode M stand-in. Not production code; classroom use only.
# Run:  uvicorn capture_mock:app --host 0.0.0.0 --port 8081
import itertools, secrets
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()
SESSIONS: dict = {}
_ids = itertools.count(1)

# Flip this from the instructor console to stage L10.
WLAN0_CONNECTED = True
CONNECTED_SSID = "WLANPI-LAB"

# Canned frames. Edit to match your room; students correlate these with real scans.
FRAMES = [
    {"frameType": "beacon", "ssid": "WLANPI-LAB",   "bssid": "aa:bb:cc:00:00:01", "channel": 36, "freq": 5180, "rssi": -41},
    {"frameType": "beacon", "ssid": "CorpSecure",   "bssid": "aa:bb:cc:00:00:02", "channel": 36, "freq": 5180, "rssi": -44},
    {"frameType": "beacon", "ssid": "WLANPI-GUEST", "bssid": "aa:bb:cc:00:00:03", "channel":  6, "freq": 2437, "rssi": -52},
    {"frameType": "beacon", "ssid": "WLANPI-LAB",   "bssid": "dd:ee:ff:00:00:09", "channel": 11, "freq": 2462, "rssi": -71},  # L12 rogue twin
    {"frameType": "beacon", "ssid": "",             "bssid": "dd:ee:ff:00:00:0a", "channel":  1, "freq": 2412, "rssi": -63},  # L11 hidden
    # L13: co-channel neighbours on ch 6 — this is the congestion evidence
    *[{"frameType": "beacon", "ssid": f"Neighbour-{i}", "bssid": f"12:34:56:00:00:{i:02x}",
       "channel": 6, "freq": 2437, "rssi": -60 - i} for i in range(1, 9)],
]

@app.get("/api/v1/wifi/capture/sources")
def sources():
    wlan0 = {
        "sourceId": "root/wlan0", "iface": "wlan0", "namespace": "root",
        "label": "On-board Wi-Fi (managed)", "mode": "managed", "captureReady": False,
        "usable": not WLAN0_CONNECTED,
        "risk": "disrupts_connection" if WLAN0_CONNECTED else "none",
        "connected": WLAN0_CONNECTED,
        "connectedSsid": CONNECTED_SSID if WLAN0_CONNECTED else None,
        "alternatives": [{"action": "use_sibling_monitor", "sourceId": "root/wlanpi0",
                          "label": "Use monitor interface wlanpi0"}] if WLAN0_CONNECTED else [],
    }
    wlanpi0 = {
        "sourceId": "root/wlanpi0", "iface": "wlanpi0", "namespace": "root",
        "label": "On-board Wi-Fi (monitor)", "mode": "monitor", "captureReady": True,
        "usable": True, "risk": "none", "connected": False, "connectedSsid": None,
        "alternatives": [],
    }
    return {"sources": [wlan0, wlanpi0]}

class CreateSession(BaseModel):
    mode: str = "summary"
    sources: list
    filter: dict | None = None
    allowDisruptive: bool = False
    subscriberAccess: str = "token"
    autoStart: bool = True
    durationSec: int | None = None

@app.post("/api/v1/wifi/capture/sessions", status_code=201)
def create(body: CreateSession):
    picked = [s.get("sourceId") for s in body.sources]
    if "root/wlan0" in picked and WLAN0_CONNECTED and not body.allowDisruptive:
        # The teachable 409. Carries the recovery path in the body.
        raise HTTPException(409, {
            "error": "CAPTURE_SOURCE_NOT_USABLE",
            "sourceId": "root/wlan0",
            "reason": "disrupts_connection",
            "alternatives": [{"action": "use_sibling_monitor", "sourceId": "root/wlanpi0"}],
        })
    sid = f"cap-{next(_ids)}"
    SESSIONS[sid] = {"state": "running", "control": secrets.token_hex(8),
                     "subscribe": secrets.token_hex(8), "cursor": 0, "sources": picked}
    s = SESSIONS[sid]
    return {"sessionId": sid, "state": "running", "sources": picked,
            "controlToken": s["control"], "subscribeToken": s["subscribe"]}

@app.get("/api/v1/wifi/capture/sessions/{sid}")
def status(sid: str):
    s = SESSIONS.get(sid) or _missing(sid)
    return {"sessionId": sid, "state": s["state"], "frameCount": s["cursor"], "sources": s["sources"]}

@app.get("/api/v1/wifi/capture/sessions/{sid}/frames")
def frames(sid: str, limit: int = 100, since: int = 0):
    s = SESSIONS.get(sid) or _missing(sid)
    # Dribble frames out so the agent has to poll rather than get everything at once.
    start = since or s["cursor"]
    end = min(start + min(limit, 4), len(FRAMES))
    s["cursor"] = end
    return {"frames": FRAMES[start:end], "nextSince": end, "hasMore": end < len(FRAMES)}

@app.post("/api/v1/wifi/capture/sessions/{sid}/stop")
def stop(sid: str, x_capture_control_token: str | None = Header(default=None)):
    s = SESSIONS.get(sid) or _missing(sid)
    if x_capture_control_token != s["control"]:
        raise HTTPException(403, {"error": "CONTROL_TOKEN_REQUIRED"})
    s["state"] = "stopped"
    return {"sessionId": sid, "state": "stopped", "frameCount": s["cursor"]}

def _missing(sid: str):
    raise HTTPException(404, {"error": "SESSION_NOT_FOUND", "sessionId": sid})
```

### 6.1 What the mock deliberately does

| Behaviour | Which lab needs it |
|-----------|--------------------|
| `wlan0` marked `usable: false` with `alternatives` while connected | L10 — the whole lab |
| `409 CAPTURE_SOURCE_NOT_USABLE` carrying the recovery path | L10 — recovery is the competency |
| `allowDisruptive: true` **succeeds** | L10 — the fail must be possible, or the safety rule is theatre |
| Frames dribbled 4 at a time with `nextSince` | L09 — forces a real polling loop |
| Stop requires the control token | L09 — punishes discarding it at create |
| Hidden-SSID and rogue-twin frames | L11, L12 |
| Eight co-channel neighbours on ch 6 | L13 — the congestion evidence |

### 6.2 Instructor console

- **Stage L10:** set `WLAN0_CONNECTED = True` (default). Set `False` to run L09 cleanly first.
- **Check for orphans:** `curl -s localhost:8081/api/v1/wifi/capture/sessions/cap-1` — any session still `running` at the end of a lab is a cleanup fail for that pair.
- **Reset between groups:** restart the process. State is in memory by design.

### 6.3 Limits — know these before a student finds them

No auth (add a bearer check if your MCP client requires one), no real channel hopping, no rate limiting, frames are fixed rather than time-ordered, and `filter` is accepted but ignored — so `frameFilter: "beacons"` does not actually change the output. That last one means **you** must check the request body to grade whether the agent set `stripPayload: true`, rather than inferring it from the response.

---

## 7. Reset between groups

```bash
# On each Pi
curl -sX POST http://$H:$P/api/v1/utils/blinker/stop
curl -s http://$H:$P/api/v1/network/config/          # list, then deactivate each active id
curl -sX POST http://$H:$P/api/v1/network/config/deactivate/<id>
resolvectl revert eth0                                # undo L02 / L07(b)
ethtool -s eth0 autoneg on                            # undo L04
timedatectl set-ntp true                              # undo L14 clock skew
```

Then re-run the §4 pre-flight. Restart the capture mock. Re-seal the envelopes.

**Most common leftovers:** an active NetConfig from L06 (the next group's L06 then behaves strangely), a skewed clock, and a black-holed resolver.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401` on every call | No valid bearer for the MCP client | Re-issue via the device-local pairing flow; confirm the client stores the token |
| `409` on hotspot endpoints | Pi is in classic mode | **Correct behaviour** — this is lab S1's lesson |
| Scan returns `422 NO_SCAN_ADAPTER` | No suitable radio; adapter in the wrong mode or claimed by another process | Check `GET /network/config/status` for the adapter layout |
| Scan returns `409 SCAN_IN_PROGRESS` | Two pairs scanning the same adapter, or the agent looping | Coalesce and retry. Not an adapter-selection problem |
| `needsSelection` never fires | Only one monitor-capable radio | L05 needs the USB adapter |
| Speedtest `503` | LibreSpeed unreachable or timed out | Check WAN. Report as a **tool** failure to the class — this is L08's trap |
| `bssLoad` missing from all scans | AP not advertising the BSS Load IE | Enable it, or fall back to neighbour count and RSSI for L08/L13 |
| Guest looks fine | Load generator stopped | Restart it and re-verify with `?detail=full` |
| Agent silently reuses stale data | Long context, earlier scan results in the transcript | Have the pair start a fresh session for the capstone |
| Pi unreachable mid-lab | Someone captured on the connected interface | That is L10's lesson, delivered the hard way. Reconnect over Ethernet |

---

## 9. Safety, legal and privacy

**Packet capture in a classroom records the neighbours' networks too.** This is not hypothetical — in a shared building you will capture frames from tenants who have not consented.

- Every MCP capture start in this pack uses `frameFilter: "beacons"` and `stripPayload: true`. Beacons are broadcast management frames. **Do not widen to `beacons_and_data` unless you own the RF environment**, and if you do, say so explicitly to the class.
- Keep `subscriberAccess` at its default (`token`). `public` exists for demos and should stay off in a room of strangers.
- Do not put real credentials in chat transcripts. The lab PSK is disposable and rotates between deliveries; treat it as such.
- Do not have students `POST /system/reg-domain/set`. Regulatory domain is a legal setting and the instructor owns it.
- Agent transcripts may be retained by the MCP client vendor. Tell students before they start, and do not run this pack against a customer's production network.

---

## 10. Reusing this pack

- Rotate the lab PSK and the rogue twin's BSSID between deliveries.
- Vary the L07 and L14 guest faults so a second cohort cannot inherit answers.
- Collect the completed lab guides. The **Audit** boxes are the best signal you will get about which agent behaviours the room actually internalised, and they tell you which trap to strengthen next time.
- When capture REST ships, retire §6 and re-verify §3's staging against the real API. The lab text does not change — that is deliberate.

| Date | Change |
|------|--------|
| 2026-08-16 | First version, alongside the restructured lab plan and student guide. |
