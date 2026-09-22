#!/usr/bin/env python3
"""Stalled capture subscriber probe.

Authenticates, subscribes to a running capture session, reads normally for a
warmup, then stops reading for --stall seconds to provoke server-side
backpressure, then resumes. Reports whether the server evicted the subscriber
with close code 1013 and how many bytes and messages it received.

A small --rcvbuf and a low --max-queue make the server block quickly; without
them, kernel socket buffers absorb short stalls and mask the eviction.

Run it directly, or through run_on_device.py which starts the owner capture and
parses the session id for you.
"""

import argparse
import asyncio
import json
import socket
import ssl
import time

import websockets


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", required=True, help="full wss:// URL of the capture endpoint")
    p.add_argument("--ca-cert", required=True, help="CA/certificate file for wss://")
    p.add_argument("--token", required=True, help="wlanpi-core JWT")
    p.add_argument("--session", required=True, help="session id to subscribe to")
    p.add_argument("--host", default="127.0.0.1", help="host for the TCP connect")
    p.add_argument("--port", type=int, default=31415, help="port for the TCP connect")
    p.add_argument("--stall", type=float, default=0.0, help="seconds to stop reading")
    p.add_argument("--warmup", type=float, default=1.0, help="seconds of normal read")
    p.add_argument("--duration", type=float, default=5.0, help="read after the stall")
    p.add_argument("--rcvbuf", type=int, default=524288, help="SO_RCVBUF, 0 for default")
    p.add_argument("--max-queue", type=int, default=64, help="client message buffer")
    p.add_argument("--label", default="sub", help="prefix for output lines")
    a = p.parse_args()

    ctx = ssl.create_default_context(cafile=a.ca_cert)
    sock = None
    if a.rcvbuf > 0:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, a.rcvbuf)
        sock.connect((a.host, a.port))

    async with websockets.connect(
        a.url,
        ssl=ctx,
        sock=sock,
        max_queue=a.max_queue,
        ping_interval=None,
        max_size=None,
    ) as ws:
        await ws.send(json.dumps({"command": "auth", "token": a.token}))
        while True:
            m = await ws.recv()
            if isinstance(m, bytes):
                continue
            e = json.loads(m)
            if e.get("code") == "AUTH_OK":
                break
            if e.get("event") == "error":
                print(f"{a.label} AUTH_ERR {e}", flush=True)
                return
        await ws.send(json.dumps({"command": "subscribe", "session_id": a.session}))
        while True:
            m = await ws.recv()
            if isinstance(m, bytes):
                continue
            e = json.loads(m)
            if e.get("code") == "SUBSCRIBED":
                break
            if e.get("event") == "error":
                print(f"{a.label} SUB_ERR {e}", flush=True)
                return

        t0 = time.monotonic()
        nbytes = 0
        nmsgs = 0
        print(f"{a.label} SUBSCRIBED warmup={a.warmup}s stall={a.stall}s", flush=True)

        async def drain(seconds: float, count: bool) -> None:
            nonlocal nbytes, nmsgs
            try:
                async with asyncio.timeout(seconds):
                    while True:
                        m = await ws.recv()
                        if isinstance(m, bytes):
                            if count:
                                nbytes += len(m)
                                nmsgs += 1
            except TimeoutError:
                return

        try:
            await drain(a.warmup, True)
            print(
                f"{a.label} STALL_BEGIN at {time.monotonic()-t0:.2f}s "
                f"bytes={nbytes} msgs={nmsgs}",
                flush=True,
            )
            if a.stall:
                await asyncio.sleep(a.stall)
            print(
                f"{a.label} STALL_END at {time.monotonic()-t0:.2f}s "
                f"bytes={nbytes} msgs={nmsgs}",
                flush=True,
            )
            await drain(a.duration, True)
            print(
                f"{a.label} NO_CLOSE survived to {time.monotonic()-t0:.2f}s "
                f"bytes={nbytes} msgs={nmsgs}",
                flush=True,
            )
        except websockets.exceptions.ConnectionClosed as ex:
            print(
                f"{a.label} CLOSED code={ex.code} reason={ex.reason!r} "
                f"at {time.monotonic()-t0:.2f}s bytes={nbytes} msgs={nmsgs}",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
