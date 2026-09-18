#!/usr/bin/env python3
"""Deterministic subscriber buffering test: old vs new constants.

Drives ConnectionManager._broadcast_chunk at a fixed block rate with one
subscriber whose first send_bytes stalls for a controlled duration. The two
eviction triggers are queue overflow (QueueFull) and send stall (TimeoutError),
both of which close the subscriber with 1013.

Run with the package importable, for example from the repo root:

    python tools/capture_harness/subscriber_buffering/budget_test.py

It imports wlanpi_core.streaming.connection_manager and monkeypatches
_SUBSCRIBER_QUEUE_BLOCKS and _SUBSCRIBER_SEND_TIMEOUT_SEC in-process, so it
needs no device and no WebSocket.
"""

import asyncio
import struct
import time

from wlanpi_core.streaming import connection_manager
from wlanpi_core.streaming.connection_manager import ConnectionManager


def block(block_type, body=b""):
    body += b"\x00" * (-len(body) % 4)
    total = len(body) + 12
    return struct.pack("<II", block_type, total) + body + struct.pack("<I", total)


PCAPNG_HEADER = block(
    0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)
) + block(1, struct.pack("<HHI", 127, 0, 65535))


def packet(payload=b"x" * 200):
    body = struct.pack("<IIIII", 0, 0, 0, len(payload), len(payload)) + payload
    return block(6, body)


class FakeWS:
    def __init__(self, stall=0.0):
        self.stall = stall
        self._stalled = False
        self.bytes_sent = 0
        self.closed = None

    async def accept(self):
        pass

    async def send_text(self, text):
        pass

    async def send_bytes(self, data):
        if self.stall and not self._stalled:
            self._stalled = True
            await asyncio.sleep(self.stall)
        self.bytes_sent += 1

    async def close(self, code=None, reason=None):
        self.closed = (code, reason)


async def run_case(label, rate, stall, queue, timeout, max_time):
    connection_manager._SUBSCRIBER_QUEUE_BLOCKS = queue
    connection_manager._SUBSCRIBER_SEND_TIMEOUT_SEC = timeout

    mgr = ConnectionManager()
    owner = FakeWS()
    sub = FakeWS(stall=stall)
    await mgr.connect(owner)
    await mgr.connect(sub)

    oclient = mgr.clients[owner]
    oclient["session_id"] = "cap_test"
    oclient["session_config"] = {"interfaces": {"wlan0": {}}, "pcap_filter": ""}
    oclient["namespace"] = None
    oclient["pcapng_endian"] = "little"
    oclient["pcapng_header_complete"] = True
    mgr.sessions["cap_test"] = owner

    await mgr.subscribe(sub, "cap_test")
    task = mgr.clients[sub]["subscription_task"]

    pkt = packet()
    interval = 1.0 / rate
    start = time.monotonic()
    fed = 0
    evicted_at = None
    while fed < 20000 and time.monotonic() - start < max_time:
        await mgr._broadcast_chunk(owner, oclient, pkt)
        fed += 1
        if sub not in oclient["subscribers"]:
            evicted_at = fed
            break
        await asyncio.sleep(interval)

    elapsed = time.monotonic() - start
    if not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.5)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    evicted = evicted_at is not None
    print(
        f"{label:12} q={queue:5} t={timeout:4} R={rate:5} stall={stall:5} "
        f"-> {'EVICT' if evicted else 'SURVIVE':7} fed={fed:5} "
        f"elapsed={elapsed:6.3f}s close={sub.closed} owner_sent={owner.bytes_sent}"
    )
    return evicted


async def main():
    cases = [
        ("case1", 2000, 0.3, 4.0),
        ("case2", 50, 3.0, 9.0),
        ("case3", 2000, 10.0, 4.0),
        ("case4", 2000, 0.6, 4.0),
    ]
    for tag, q, t in (("OLD", 128, 1.0), ("NEW", 1024, 5.0)):
        print(f"=== {tag} constants (queue={q}, timeout={t}) ===")
        for label, rate, stall, mt in cases:
            await run_case(f"{tag}/{label}", rate, stall, q, t, mt)
    print(
        "\nR is nominal. asyncio.sleep overhead makes the effective feed rate "
        "lower (~800 blocks/s here); the relative behavior is the point."
    )


if __name__ == "__main__":
    asyncio.run(main())
