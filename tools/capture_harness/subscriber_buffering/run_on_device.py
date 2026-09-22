#!/usr/bin/env python3
"""Run owner capture plus stalled-subscriber cases against a device.

Starts capture_harness.py as the owner, reads the session id from its output,
then runs slow_subscriber.py once per stall value, sequentially, and prints
each probe result. Use it to compare the capture subscriber queue budget
between two builds (deploy one, run, deploy the other, run).

Example:

    python run_on_device.py \
        --url wss://wlanpi.local:31415/api/v1/streaming/capture \
        --ca-cert /etc/nginx/ssl/self-signed-wlanpi.cert \
        --token-file /tmp/token --config /tmp/ch6.json \
        --build OLD --stalls 0 3 5 10
"""

import argparse
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def run_case(a, token, stall):
    label = f"{a.build}/stall={stall}"
    time.sleep(3)
    owner = subprocess.Popen(
        [
            a.python,
            "-u",
            a.harness,
            "run",
            "--config",
            a.config,
            "--url",
            a.url,
            "--ca-cert",
            a.ca_cert,
            "--token",
            token,
            "--duration",
            str(a.owner_seconds),
            "--refresh",
            "3600",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    session = None
    try:
        for line in owner.stdout:
            if "CAPTURE SESSION:" in line:
                session = line.split(":")[-1].strip()
                break
        if not session:
            print(f"{label} OWNER_FAILED")
            return
        sub = subprocess.run(
            [
                a.python,
                "-u",
                a.probe,
                "--url",
                a.url,
                "--ca-cert",
                a.ca_cert,
                "--token",
                token,
                "--session",
                session,
                "--host",
                a.host,
                "--port",
                str(a.port),
                "--stall",
                str(stall),
                "--warmup",
                str(a.warmup),
                "--duration",
                str(a.duration),
                "--label",
                label,
            ],
            capture_output=True,
            text=True,
            timeout=a.owner_seconds + 8,
        )
        for line in sub.stdout.splitlines():
            print(line)
        if sub.stderr.strip():
            print(f"{label} STDERR {sub.stderr.strip()[:300]}")
    finally:
        try:
            os.killpg(os.getpgid(owner.pid), signal.SIGTERM)
        except Exception:
            pass
        try:
            owner.wait(timeout=10)
        except Exception:
            pass


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", required=True)
    p.add_argument("--ca-cert", required=True)
    p.add_argument("--config", required=True, help="capture config JSON for the owner")
    p.add_argument("--token", help="wlanpi-core JWT")
    p.add_argument("--token-file", help="file containing the JWT")
    p.add_argument("--host", default="127.0.0.1", help="host for the probe TCP connect")
    p.add_argument("--port", type=int, default=31415)
    p.add_argument("--build", default="build", help="label for this build")
    p.add_argument("--stalls", type=float, nargs="+", default=[0.0, 3.0, 5.0, 10.0])
    p.add_argument("--warmup", type=float, default=1.0)
    p.add_argument("--duration", type=float, default=5.0)
    p.add_argument("--owner-seconds", type=float, default=22.0)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--harness", default=os.path.join(HERE, "..", "capture_harness.py"))
    p.add_argument("--probe", default=os.path.join(HERE, "slow_subscriber.py"))
    a = p.parse_args()

    token = a.token
    if not token and a.token_file:
        token = open(a.token_file).read().strip()
    if not token:
        token = os.environ.get("WLANPI_CAP_TOKEN", "")
    if not token:
        sys.exit("no token: pass --token, --token-file, or WLANPI_CAP_TOKEN")

    for stall in a.stalls:
        run_case(a, token, stall)


if __name__ == "__main__":
    main()
