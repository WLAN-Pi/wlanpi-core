# -*- coding: utf-8 -*-
#
# wlanpi-core : backend services for the WLAN Pi
# Copyright : (c) 2026 Josh Schmelzle
# License : BSD-3-Clause
# Maintainer : josh@joshschmelzle.com

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"

COMMAND_TIMEOUT_SEC = 10


def run(cmd: list[str]) -> str:
    """Run a command and return its combined stdout/stderr output."""
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=COMMAND_TIMEOUT_SEC,
        )
        return res.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"Failed to run command {' '.join(cmd)}: {e}"


def read_file(path_str: str) -> str:
    try:
        return Path(path_str).read_text()
    except OSError as e:
        return f"Error reading {path_str}: {e}"


def section(report: list[str], title: str) -> None:
    report.append("-" * 80)
    report.append(title)
    report.append("-" * 80)


def generate_report() -> str:
    report = []

    # Header
    report.append("=" * 80)
    report.append("WLAN PI TECHNICAL SUPPORT DIAGNOSTIC REPORT")
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 80)
    report.append("")

    # 1. OS and Kernel Info
    section(report, "1. OS and Kernel Information")
    report.append(f"uname -a:\n{run(['uname', '-a'])}")
    report.append(f"/etc/os-release:\n{read_file('/etc/os-release')}")
    report.append(f"/etc/debian_version:\n{read_file('/etc/debian_version')}")
    report.append(f"/etc/wlanpi-release:\n{read_file('/etc/wlanpi-release')}")
    report.append("")

    # 2. System Resources
    section(report, "2. System Resources")
    report.append(f"uptime:\n{run(['uptime'])}")
    report.append(f"free -h:\n{run(['free', '-h'])}")
    report.append(f"df -h:\n{run(['df', '-h'])}")
    report.append("")

    # 3. WLAN Pi Packages
    section(report, "3. WLAN Pi Packages (wlanpi-*)")
    report.append(run(["dpkg", "-l", "wlanpi-*"]))
    report.append("")

    # 4. Network Configuration
    section(report, "4. Network Configuration")
    report.append(f"ip addr:\n{run(['ip', 'addr'])}")
    report.append(f"ip route:\n{run(['ip', 'route'])}")
    report.append("")

    # 5. Wireless Interfaces and Capabilities
    section(report, "5. Wireless Interfaces and Capabilities")
    report.append(f"iw dev:\n{run(['iw', 'dev'])}")
    report.append(f"iw phy:\n{run(['iw', 'phy'])}")
    report.append("")

    # 6. USB Devices
    section(report, "6. USB Devices (lsusb)")
    report.append(run(["lsusb"]))
    report.append("")

    # 7. Loaded Kernel Modules
    section(report, "7. Loaded Kernel Modules (lsmod)")
    report.append(run(["lsmod"]))
    report.append("")

    # 8. WLAN Pi Services Status
    section(report, "8. WLAN Pi Services Status")
    services = ["wlanpi-core", "wlanpi-webui", "wlanpi-fpms", "wlanpi-profiler"]
    for service in services:
        report.append(
            f"systemctl status {service}:\n"
            f"{run(['systemctl', 'status', service, '--no-pager'])}"
        )
        report.append("")

    # 9. Recent dmesg logs
    section(report, "9. Recent dmesg logs (filtered/tail)")
    report.append(run(["dmesg", "-T", "--level=err,warn"]))
    dmesg_tail = "\n".join(run(["dmesg", "-T"]).splitlines()[-50:])
    report.append(f"\nLast 50 lines of dmesg:\n{dmesg_tail}")
    report.append("")

    # 10. wlanpi-core Journal
    section(report, "10. Recent wlanpi-core logs")
    report.append(run(["journalctl", "-u", "wlanpi-core", "-n", "50", "--no-pager"]))
    report.append("")

    return "\n".join(report)


def main(argv: Optional[list[str]] = None) -> int:
    # ip, iw, and lsmod live in sbin, which non-root PATHs often omit
    os.environ["PATH"] = os.environ.get("PATH", "") + ":/usr/sbin:/sbin"

    parser = argparse.ArgumentParser(
        description="Gather WLAN Pi diagnostics and tech support information"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        help="Path to save the report locally",
    )
    parser.add_argument(
        "--paste",
        metavar="URL",
        type=str,
        help="POST the report as text/plain to URL (e.g. a self-hosted pastebin) "
        "and print the server response",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colorized output messages",
    )

    args = parser.parse_args(argv)

    if args.no_color:
        global RED, GREEN, YELLOW, BLUE, NC
        RED = GREEN = YELLOW = BLUE = NC = ""

    if os.geteuid() != 0:
        print(
            f"{YELLOW}[!]{NC} Not running as root; dmesg/journalctl output may "
            "be incomplete. Re-run with sudo."
        )

    print(f"{BLUE}[*]{NC} Gathering diagnostics report (may take a few seconds)...")
    report = generate_report()

    if args.file:
        try:
            path = Path(args.file)
            path.write_text(report)
            print(f"{GREEN}[+]{NC} Report saved locally to {path.resolve()}")
        except OSError as e:
            print(f"{RED}[-]{NC} Failed to save report to file: {e}")
            return 1

    if args.paste:
        print(f"{BLUE}[*]{NC} Uploading report to {args.paste} ...")
        try:
            resp = requests.post(
                args.paste,
                data=report.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"{RED}[-]{NC} Upload to {args.paste} failed: {e}")
            return 1
        print(f"{GREEN}[+]{NC} Server response: {resp.text.strip()}")

    if not args.file and not args.paste:
        print(report)

    return 0


if __name__ == "__main__":
    exit(main())
