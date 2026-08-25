#!/usr/bin/env python3
"""
wlanpi-core capture WebSocket test harness.

Two modes:

  config   Build a reusable capture config (adapter, channels, dwell, filter)
           and write it to JSON. No device contact.

  run      Connect to the capture WebSocket, authenticate, then EITHER start a
           capture from a config file (owner) OR subscribe read-only to an
           existing session. Dissects the live pcapng stream and prints a
           rolling AP scan (SSID, BSSID, channel, signal, security, PHY
           amendments, TX power).

  list     Authenticate and print the running capture sessions.

Run several instances at once: one `run --config ...` owns a capture and prints
its session id; another `run --subscribe <session_id>` listens in read-only.

Dependencies: websockets (`pip install websockets`). The dissector is built in.

Auth: the token is a wlanpi-core JWT. Get one on the device with
`sudo getjwt <name> -p <port> --no-color` and read the "access_token" field.
Pass it with --token or the WLANPI_CAP_TOKEN environment variable. Tokens are
NEVER placed in the URL (the server refuses that; query strings get logged).

Transport note: connect straight to the dev/app server port (e.g.
ws://wlanpi.local:8000/api/v1/streaming/capture). nginx TLS front-ends do not
yet forward the WebSocket upgrade, so wss:// through nginx will not work until
that lands.

Dissector limitations (documented on purpose; this is a test tool, not
Wireshark): radiotap parsing reads the first present-word only (covers channel,
signal, TX power); IE parsing covers SSID, DS channel, country, RSN/WPA, HT/VHT/
HE/EHT presence, and TPC report TX power.
"""

import argparse
import asyncio
import json
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import websockets
except ImportError:
    sys.exit("This harness needs the 'websockets' package: pip install websockets")

DEFAULT_URL = "ws://localhost:8000/api/v1/streaming/capture"
AUTH_TIMEOUT = 10.0

# ---------------------------------------------------------------------------
# Channel / frequency helpers
# ---------------------------------------------------------------------------


def channel_to_freq(ch: int) -> int:
    if ch == 14:
        return 2484
    if 1 <= ch <= 13:
        return 2412 + (ch - 1) * 5
    if 32 <= ch <= 196:  # 5 GHz
        return 5000 + ch * 5
    raise ValueError(f"cannot map channel {ch} to a frequency; use --freqs for 6 GHz")


def freq_to_channel(freq: int) -> Optional[int]:
    if freq == 2484:
        return 14
    if 2412 <= freq <= 2472:
        return (freq - 2412) // 5 + 1
    if 5000 <= freq <= 5895:
        return (freq - 5000) // 5
    if 5955 <= freq <= 7115:  # 6 GHz
        return (freq - 5950) // 5
    return None


# ---------------------------------------------------------------------------
# pcapng stream reader (incremental; chunks arrive unaligned)
# ---------------------------------------------------------------------------


class PcapngReader:
    """Feed arbitrary byte chunks; yields (linktype, packet_bytes) per packet."""

    SHB = 0x0A0D0D0A
    IDB = 0x00000001
    EPB = 0x00000006

    def __init__(self) -> None:
        self.buf = bytearray()
        self.endian = "<"
        self.linktypes: Dict[int, int] = {}
        self._iface_seq = 0

    def feed(self, data: bytes) -> List[Tuple[int, bytes]]:
        self.buf += data
        out: List[Tuple[int, bytes]] = []
        while len(self.buf) >= 12:
            if bytes(self.buf[0:4]) == b"\x0a\x0d\x0d\x0a":
                bom = bytes(self.buf[8:12])
                if bom == b"\x4d\x3c\x2b\x1a":
                    self.endian = "<"
                elif bom == b"\x1a\x2b\x3c\x4d":
                    self.endian = ">"
            total_len = struct.unpack(self.endian + "I", self.buf[4:8])[0]
            if total_len < 12 or total_len % 4 != 0:
                # Desynced; drop a byte and try to re-find a block boundary.
                self.buf.pop(0)
                continue
            if len(self.buf) < total_len:
                break
            block = bytes(self.buf[:total_len])
            del self.buf[:total_len]
            self._handle_block(block, out)
        return out

    def _handle_block(self, block: bytes, out: List[Tuple[int, bytes]]) -> None:
        e = self.endian
        btype = struct.unpack_from(e + "I", block, 0)[0]
        if btype == self.SHB:
            # New section: interface numbering restarts.
            self.linktypes = {}
            self._iface_seq = 0
        elif btype == self.IDB:
            linktype = struct.unpack_from(e + "H", block, 8)[0]
            self.linktypes[self._iface_seq] = linktype
            self._iface_seq += 1
        elif btype == self.EPB:
            if len(block) < 28:
                return
            iface_id = struct.unpack_from(e + "I", block, 8)[0]
            caplen = struct.unpack_from(e + "I", block, 20)[0]
            pkt = block[28 : 28 + caplen]
            out.append((self.linktypes.get(iface_id, 127), pkt))


# ---------------------------------------------------------------------------
# Radiotap + 802.11 dissection
# ---------------------------------------------------------------------------

# (align, size) for radiotap present bits 0..14 - enough for our targets.
_RT_FIELDS = {
    0: (8, 8), 1: (1, 1), 2: (1, 1), 3: (2, 4), 4: (2, 2), 5: (1, 1),
    6: (1, 1), 7: (2, 2), 8: (2, 2), 9: (2, 2), 10: (1, 1), 11: (1, 1),
    12: (1, 1), 13: (1, 1), 14: (2, 2),
}


def parse_radiotap(buf: bytes) -> Tuple[dict, int]:
    """Return ({freq, signal, txpower}, header_len). header_len 0 on failure."""
    info = {"freq": None, "signal": None, "txpower": None}
    if len(buf) < 8:
        return info, 0
    _ver, _pad, length = struct.unpack_from("<BBH", buf, 0)
    if length < 8 or length > len(buf):
        return info, 0
    present_words = []
    off = 4
    while off + 4 <= len(buf):
        word = struct.unpack_from("<I", buf, off)[0]
        present_words.append(word)
        off += 4
        if not (word & (1 << 31)):
            break
    if not present_words:
        return info, length
    pos = off
    present = present_words[0]
    for bit in range(0, 15):
        if not (present & (1 << bit)):
            continue
        align, size = _RT_FIELDS[bit]
        if pos % align:
            pos += align - (pos % align)
        if pos + size > length:
            break
        if bit == 3:
            info["freq"] = struct.unpack_from("<H", buf, pos)[0]
        elif bit == 5:
            info["signal"] = struct.unpack_from("<b", buf, pos)[0]
        elif bit == 10:
            info["txpower"] = struct.unpack_from("<b", buf, pos)[0]
        pos += size
    return info, length


_OUI_RSN = b"\x00\x0f\xac"
_OUI_MS = b"\x00\x50\xf2"


def _rsn_security(val: bytes) -> str:
    try:
        off = 2 + 4  # version + group cipher
        pw_count = int.from_bytes(val[off : off + 2], "little")
        off += 2 + 4 * pw_count
        akm_count = int.from_bytes(val[off : off + 2], "little")
        off += 2
        akm_types = set()
        for _ in range(akm_count):
            suite = val[off : off + 4]
            off += 4
            if suite[:3] == _OUI_RSN:
                akm_types.add(suite[3])
        has_sae = bool(akm_types & {8, 9})
        has_psk = bool(akm_types & {2, 4, 6})
        has_ent = bool(akm_types & {1, 3, 5})
        if has_sae and has_psk:
            return "WPA2/3"
        if has_sae:
            return "WPA3"
        if has_ent:
            return "WPA2-Ent"
        if has_psk:
            return "WPA2-PSK"
        return "WPA2"
    except Exception:
        return "WPA2"


@dataclass
class ApInfo:
    bssid: str = ""
    ssid: str = ""
    channel: Optional[int] = None
    signal: Optional[int] = None
    security: str = "Open"
    phy: set = field(default_factory=set)
    txpower: Optional[int] = None
    country: str = ""
    count: int = 0
    last_seen: float = 0.0


def parse_beacon(pkt: bytes, radio: dict) -> Optional[ApInfo]:
    """Parse a management beacon/probe-response into ApInfo, else None."""
    rt_info, rtlen = parse_radiotap(pkt)
    if rtlen == 0:
        return None
    if len(pkt) < rtlen + 24:
        return None
    fc = struct.unpack_from("<H", pkt, rtlen)[0]
    ftype = (fc >> 2) & 0x3
    subtype = (fc >> 4) & 0xF
    if ftype != 0 or subtype not in (5, 8):  # mgmt beacon(8)/probe-resp(5)
        return None

    ap = ApInfo()
    ap.bssid = ":".join(f"{b:02x}" for b in pkt[rtlen + 16 : rtlen + 22])
    ap.signal = rt_info.get("signal")
    ap.txpower = rt_info.get("txpower")
    if rt_info.get("freq"):
        ap.channel = freq_to_channel(rt_info["freq"])

    # capability info (privacy bit) then tagged IEs
    caps_off = rtlen + 24 + 8 + 2  # + timestamp(8) + interval(2)
    privacy = False
    if caps_off + 2 <= len(pkt):
        caps = struct.unpack_from("<H", pkt, caps_off)[0]
        privacy = bool(caps & 0x0010)

    p = rtlen + 24 + 12
    end = len(pkt)
    have_rsn = have_wpa = False
    while p + 2 <= end:
        tag = pkt[p]
        ln = pkt[p + 1]
        val = pkt[p + 2 : p + 2 + ln]
        p += 2 + ln
        if len(val) < ln:
            break
        if tag == 0:
            ap.ssid = val.decode("utf-8", "replace") if val else "<hidden>"
        elif tag == 3 and val:
            ap.channel = val[0]
        elif tag == 7 and len(val) >= 2:
            ap.country = val[:2].decode("ascii", "replace")
        elif tag == 35 and val:  # TPC report: tx power, link margin
            ap.txpower = struct.unpack_from("<b", val, 0)[0]
        elif tag == 45:
            ap.phy.add("n")
        elif tag == 48:
            have_rsn = True
            ap.security = _rsn_security(val)
        elif tag == 191:
            ap.phy.add("ac")
        elif tag == 221 and val[:3] == _OUI_MS and len(val) >= 4 and val[3] == 1:
            have_wpa = True
        elif tag == 255 and val:  # extension IEs
            ext = val[0]
            if ext in (35, 36):
                ap.phy.add("ax")
            elif ext in (106, 108):
                ap.phy.add("be")

    if not have_rsn:
        if have_wpa:
            ap.security = "WPA"
        elif privacy:
            ap.security = "WEP"
        else:
            ap.security = "Open"
    return ap


_PHY_ORDER = ["n", "ac", "ax", "be"]


def phy_label(ap: ApInfo) -> str:
    base = "g" if (ap.channel or 0) <= 14 else "a"
    amend = [x for x in _PHY_ORDER if x in ap.phy]
    return "/".join([base] + amend)


# ---------------------------------------------------------------------------
# Scan table
# ---------------------------------------------------------------------------


class ScanTable:
    def __init__(self) -> None:
        self.aps: Dict[str, ApInfo] = {}
        self.other = 0

    def update(self, ap: ApInfo) -> None:
        existing = self.aps.get(ap.bssid)
        if existing is None:
            ap.count = 1
            ap.last_seen = time.monotonic()
            self.aps[ap.bssid] = ap
            return
        existing.count += 1
        existing.last_seen = time.monotonic()
        if ap.ssid and ap.ssid != "<hidden>":
            existing.ssid = ap.ssid
        if ap.channel:
            existing.channel = ap.channel
        if ap.signal is not None:
            existing.signal = ap.signal
        if ap.txpower is not None:
            existing.txpower = ap.txpower
        if ap.country:
            existing.country = ap.country
        if ap.security != "Open":
            existing.security = ap.security
        existing.phy |= ap.phy

    def render(self) -> str:
        rows = sorted(
            self.aps.values(),
            key=lambda a: (a.channel or 999, -(a.signal or -999)),
        )
        lines = [
            f"{'BSSID':<17} {'CH':>3} {'SIG':>4} {'SEC':<9} "
            f"{'PHY':<11} {'TXP':>4} {'CC':<3} {'#':>5}  SSID"
        ]
        lines.append("-" * 78)
        for a in rows:
            lines.append(
                f"{a.bssid:<17} {str(a.channel or '?'):>3} "
                f"{str(a.signal if a.signal is not None else '?'):>4} "
                f"{a.security:<9} {phy_label(a):<11} "
                f"{str(a.txpower if a.txpower is not None else '?'):>4} "
                f"{a.country:<3} {a.count:>5}  {a.ssid[:32]}"
            )
        lines.append(
            f"\n{len(self.aps)} AP(s), {self.other} non-beacon frame(s)"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------


def resolve_token(args) -> str:
    if args.token:
        return args.token
    env = os.environ.get(args.token_env)
    if env:
        return env
    sys.exit(
        f"No token. Pass --token or set ${args.token_env}. "
        "Get one with: sudo getjwt <name> -p <port> --no-color"
    )


async def _authenticate(ws, token: str) -> str:
    await ws.send(json.dumps({"command": "auth", "token": token}))
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
        if isinstance(msg, bytes):
            continue
        event = json.loads(msg)
        code = event.get("code")
        if code == "AUTH_OK":
            return event.get("data", {}).get("did", "?")
        raise RuntimeError(f"auth failed: {code} {event.get('data')}")


async def _consume(ws, table: ScanTable, refresh: float, deadline: Optional[float],
                   raw_fp) -> None:
    reader = PcapngReader()
    last_print = 0.0
    while True:
        if deadline and time.monotonic() >= deadline:
            return
        timeout = refresh
        if deadline:
            timeout = min(refresh, max(0.05, deadline - time.monotonic()))
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            msg = None
        if isinstance(msg, bytes):
            if raw_fp:
                raw_fp.write(msg)
            for linktype, pkt in reader.feed(msg):
                radio = {}
                ap = parse_beacon(pkt, radio)
                if ap:
                    table.update(ap)
                else:
                    table.other += 1
        elif isinstance(msg, str):
            event = json.loads(msg)
            code = event.get("code", "")
            data = event.get("data", {})
            if code not in ("CHANNEL_SET",):  # keep hop spam down
                note = data.get("message") or data
                print(f"[event] {code}: {note}", file=sys.stderr)
            if code in ("CAPTURE_ENDED", "CAPTURE_STOPPED"):
                # The capture is over (owner stopped, or dumpcap exited);
                # stop consuming instead of idling on a dead session.
                print("[capture ended] stopping.", file=sys.stderr)
                return
        now = time.monotonic()
        if now - last_print >= refresh:
            print("\n" + table.render())
            last_print = now


def _print_config(config: Optional[dict]) -> None:
    if not config:
        print("  (running config unavailable)")
        return
    for iface, cfg in (config.get("interfaces") or {}).items():
        chans = ",".join(
            str(freq_to_channel(c["freq"]) or c["freq"])
            for c in cfg.get("channels", [])
        )
        print(f"  {iface}: channels [{chans}] dwell {cfg.get('dwell_time')}ms")
    if config.get("pcap_filter"):
        print(f"  filter: {config['pcap_filter']}")


async def _find_sessions(ws) -> list:
    await ws.send(json.dumps({"command": "list_sessions"}))
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
        if isinstance(msg, bytes):
            continue
        event = json.loads(msg)
        if event.get("code") == "SESSIONS":
            return event.get("data", {}).get("sessions", [])


async def run_owner(args) -> None:
    token = resolve_token(args)
    with open(args.config) as fh:
        config = json.load(fh)
    interfaces = config["interfaces"]
    pcap_filter = config.get("pcap_filter", "")

    async with websockets.connect(args.url, max_size=None) as ws:
        did = await _authenticate(ws, token)
        print(f"[auth] authenticated as did={did}", file=sys.stderr)

        # Own-vs-subscribe pre-flight: if a capture is already running on an
        # interface we want, tell the user they could subscribe instead.
        wanted = set(interfaces.keys())
        for sess in await _find_sessions(ws):
            clash = wanted & set(sess.get("interfaces", []))
            if clash:
                print(
                    f"[note] {sorted(clash)} already captured by session "
                    f"{sess['session_id']} (owner did={sess.get('owner')}). "
                    f"start will fail with INTERFACE_IN_USE; to observe it run:\n"
                    f"    run --subscribe {sess['session_id']} --url {args.url}",
                    file=sys.stderr,
                )

        await ws.send(json.dumps({"command": "configure", "interfaces": interfaces}))
        await ws.send(
            json.dumps(
                {
                    "command": "start",
                    "interfaces": list(interfaces.keys()),
                    "pcap_filter": pcap_filter,
                }
            )
        )
        # Wait for CAPTURE_STARTED to surface the session id.
        session_id = None
        while session_id is None:
            msg = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
            if isinstance(msg, bytes):
                continue
            event = json.loads(msg)
            if event.get("code") == "CAPTURE_STARTED":
                session_id = event.get("data", {}).get("session_id")
            elif event.get("event") == "error":
                raise RuntimeError(f"start failed: {event.get('data')}")
        print("=" * 60)
        print(f"  ROLE: OWNER (in control of this capture)")
        print(f"  CAPTURE SESSION: {session_id}")
        print(f"  subscribe from another instance:")
        print(f"    capture_harness.py run --subscribe {session_id} "
              f"--url {args.url}")
        print("=" * 60)

        raw_fp = open(args.raw_out, "wb") if args.raw_out else None
        table = ScanTable()
        deadline = time.monotonic() + args.duration if args.duration else None
        try:
            await _consume(ws, table, args.refresh, deadline, raw_fp)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            try:
                await ws.send(json.dumps({"command": "stop"}))
            except Exception:
                pass
            if raw_fp:
                raw_fp.close()
                print(f"\n[raw] wrote pcapng to {args.raw_out}", file=sys.stderr)
        print("\nFINAL SCAN:\n" + table.render())


async def run_subscriber(args) -> None:
    token = resolve_token(args)
    async with websockets.connect(args.url, max_size=None) as ws:
        did = await _authenticate(ws, token)
        print(f"[auth] authenticated as did={did}", file=sys.stderr)
        await ws.send(
            json.dumps({"command": "subscribe", "session_id": args.subscribe})
        )
        # Learn the running config before consuming, so we are not blind.
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
            if isinstance(msg, bytes):
                continue
            event = json.loads(msg)
            if event.get("code") == "SUBSCRIBED":
                data = event.get("data", {})
                print("=" * 60)
                print(f"  ROLE: SUBSCRIBER (read-only, not in control)")
                ns = data.get("namespace") or "root"
                print(f"  session {args.subscribe} owned by "
                      f"did={data.get('owner')} in namespace {ns}")
                _print_config(data.get("config"))
                print("=" * 60)
                break
            if event.get("event") == "error":
                raise RuntimeError(f"subscribe failed: {event.get('data')}")
        raw_fp = open(args.raw_out, "wb") if args.raw_out else None
        table = ScanTable()
        deadline = time.monotonic() + args.duration if args.duration else None
        try:
            await _consume(ws, table, args.refresh, deadline, raw_fp)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            if raw_fp:
                raw_fp.close()
        print("\nFINAL SCAN (subscriber):\n" + table.render())


async def run_list(args) -> None:
    token = resolve_token(args)
    async with websockets.connect(args.url, max_size=None) as ws:
        await _authenticate(ws, token)
        await ws.send(json.dumps({"command": "list_sessions"}))
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
            if isinstance(msg, bytes):
                continue
            event = json.loads(msg)
            if event.get("code") == "SESSIONS":
                sessions = event.get("data", {}).get("sessions", [])
                if not sessions:
                    print("no running capture sessions")
                for sess in sessions:
                    print(
                        f"{sess['session_id']}  owner={sess.get('owner')}  "
                        f"ns={sess.get('namespace') or 'root'}  "
                        f"interfaces={','.join(sess.get('interfaces', []))}"
                    )
                    _print_config(sess.get("config"))
                return


# ---------------------------------------------------------------------------
# config builder
# ---------------------------------------------------------------------------


def build_config(args) -> None:
    channels = []
    if args.freqs:
        for f in args.freqs.split(","):
            channels.append({"freq": int(f), "width": args.width})
    if args.channels:
        for c in args.channels.split(","):
            channels.append({"freq": channel_to_freq(int(c)), "width": args.width})
    if not channels:
        sys.exit("provide --channels and/or --freqs")
    config = {
        "interfaces": {
            args.interface: {
                "channels": channels,
                "dwell_time": args.dwell,
            }
        },
        "pcap_filter": args.filter or "",
    }
    text = json.dumps(config, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}")
        print(f"  {len(channels)} channel(s) on {args.interface}, "
              f"dwell {args.dwell}ms")
    else:
        print(text)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="mode", required=True)

    pc = sub.add_parser("config", help="build a capture config JSON")
    pc.add_argument("--interface", default="wlanpi0")
    pc.add_argument("--channels", help="channel numbers, e.g. 1,6,11,36,149")
    pc.add_argument("--freqs", help="explicit MHz, e.g. 5955,5975 (6 GHz)")
    pc.add_argument("--width", type=int, default=20, choices=[20, 40, 80, 160])
    pc.add_argument("--dwell", type=int, default=250, help="dwell ms per channel")
    pc.add_argument("--filter", help="pcap/BPF filter string")
    pc.add_argument("--out", help="write to this file instead of stdout")

    def add_client_args(p):
        p.add_argument("--url", default=DEFAULT_URL)
        p.add_argument("--token", help="wlanpi-core JWT")
        p.add_argument("--token-env", default="WLANPI_CAP_TOKEN")
        p.add_argument("--refresh", type=float, default=3.0, help="table interval s")
        p.add_argument("--duration", type=float, help="stop after N seconds")
        p.add_argument("--raw-out", help="write raw pcapng stream to this file")

    pr = sub.add_parser("run", help="start or subscribe to a capture")
    add_client_args(pr)
    g = pr.add_mutually_exclusive_group(required=True)
    g.add_argument("--config", help="config JSON to start a capture (owner)")
    g.add_argument("--subscribe", help="session id to listen to (read-only)")

    pl = sub.add_parser("list", help="list running capture sessions")
    add_client_args(pl)

    args = parser.parse_args()

    if args.mode == "config":
        build_config(args)
    else:
        try:
            if args.mode == "list":
                asyncio.run(run_list(args))
            elif args.config:
                asyncio.run(run_owner(args))
            else:
                asyncio.run(run_subscriber(args))
        except KeyboardInterrupt:
            pass
        except OSError as exc:
            sys.exit(f"could not connect to {args.url}: {exc}")
        except (RuntimeError, asyncio.TimeoutError) as exc:
            sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
