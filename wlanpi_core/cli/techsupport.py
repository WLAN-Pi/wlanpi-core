# -*- coding: utf-8 -*-
#
# wlanpi-core : backend services for the WLAN Pi
# Copyright : (c) 2026 Josh Schmelzle
# License : BSD-3-Clause
# Maintainer : josh@joshschmelzle.com

import argparse
import socket
import subprocess
from datetime import datetime
from pathlib import Path

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def find_command(cmd_name: str) -> str:
    # Try running "which" first
    try:
        res = subprocess.run(
            ["which", cmd_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    # Check standard paths
    standard_paths = [
        f"/usr/bin/{cmd_name}",
        f"/usr/sbin/{cmd_name}",
        f"/bin/{cmd_name}",
        f"/sbin/{cmd_name}",
    ]
    for p in standard_paths:
        if Path(p).exists():
            return p

    return cmd_name


def run_command(cmd: list) -> str:
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10
        )
        return res.stdout
    except Exception as e:
        return f"Failed to run command {' '.join(cmd)}: {e}"


def read_file(path_str: str) -> str:
    path = Path(path_str)
    if path.exists() and path.is_file():
        try:
            return path.read_text()
        except Exception as e:
            return f"Error reading {path_str}: {e}"
    return f"File {path_str} does not exist"


def upload_to_termbin(text: str) -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect(("termbin.com", 9999))
            s.sendall(text.encode("utf-8"))
            response = s.recv(1024).decode("utf-8").strip()
            return response
    except Exception as e:
        return f"Upload to termbin failed: {e}"


def generate_report() -> str:
    report = []

    # Header
    report.append("=" * 80)
    report.append("WLAN PI TECHNICAL SUPPORT DIAGNOSTIC REPORT")
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 80)
    report.append("")

    # 1. OS and Kernel Info
    report.append("-" * 80)
    report.append("1. OS and Kernel Information")
    report.append("-" * 80)
    report.append(f"uname -a:\n{run_command(['uname', '-a'])}")
    report.append(f"/etc/os-release:\n{read_file('/etc/os-release')}")
    report.append(f"/etc/debian_version:\n{read_file('/etc/debian_version')}")
    if Path("/etc/wlanpi-release").exists():
        report.append(f"/etc/wlanpi-release:\n{read_file('/etc/wlanpi-release')}")
    report.append("")

    # 2. System Resources
    report.append("-" * 80)
    report.append("2. System Resources")
    report.append("-" * 80)
    report.append(f"uptime:\n{run_command([find_command('uptime')])}")
    report.append(f"free -h:\n{run_command([find_command('free'), '-h'])}")
    report.append(f"df -h:\n{run_command([find_command('df'), '-h'])}")
    report.append("")

    # 3. WLAN Pi Packages
    report.append("-" * 80)
    report.append("3. WLAN Pi Packages (wlanpi-*)")
    report.append("-" * 80)
    report.append(run_command([find_command("dpkg"), "-l", "wlanpi-*"]))
    report.append("")

    # 4. Network Configuration
    report.append("-" * 80)
    report.append("4. Network Configuration")
    report.append("-" * 80)
    report.append(f"ip addr:\n{run_command([find_command('ip'), 'addr'])}")
    report.append(f"ip route:\n{run_command([find_command('ip'), 'route'])}")
    report.append("")

    # 5. Wireless Interfaces and Capabilities
    report.append("-" * 80)
    report.append("5. Wireless Interfaces and Capabilities")
    report.append("-" * 80)
    iw_cmd = find_command("iw")
    if Path(iw_cmd).exists() or iw_cmd != "iw":
        report.append(f"iw dev:\n{run_command(['sudo', iw_cmd, 'dev'])}")
        report.append(f"iw phy:\n{run_command(['sudo', iw_cmd, 'phy'])}")
    else:
        report.append("iw command not found")
    report.append("")

    # 6. USB Devices
    report.append("-" * 80)
    report.append("6. USB Devices (lsusb)")
    report.append("-" * 80)
    report.append(run_command([find_command("lsusb")]))
    report.append("")

    # 7. Loaded Wireless Modules
    report.append("-" * 80)
    report.append("7. Loaded Wireless Kernel Modules (lsmod)")
    report.append("-" * 80)
    lsmod_out = run_command([find_command("lsmod")])
    wireless_mods = [
        line
        for line in lsmod_out.splitlines()
        if any(
            mod in line
            for mod in ["mt7", "rtw", "rtl", "cfg80211", "mac80211", "ath", "iwl"]
        )
    ]
    if wireless_mods:
        report.append("\n".join(wireless_mods))
    else:
        report.append("No active wireless modules detected in lsmod")
    report.append("")

    # 8. WLAN Pi Services Status
    report.append("-" * 80)
    report.append("8. WLAN Pi Services Status")
    report.append("-" * 80)
    services = ["wlanpi-core", "wlanpi-webui", "wlanpi-fpms", "wlanpi-profiler"]
    systemctl_cmd = find_command("systemctl")
    for service in services:
        report.append(
            f"systemctl status {service}:\n{run_command([systemctl_cmd, 'status', service, '--no-pager'])}"
        )
        report.append("")

    # 9. Recent dmesg logs
    report.append("-" * 80)
    report.append("9. Recent dmesg logs (filtered/tail)")
    report.append("-" * 80)
    dmesg_cmd = find_command("dmesg")
    report.append(run_command([dmesg_cmd, "-T", "--level=err,warn"]))
    report.append(f"\nLast 50 lines of dmesg:\n{run_command([dmesg_cmd, '-T'])}")
    report.append("")

    # 10. wlanpi-core Journal
    report.append("-" * 80)
    report.append("10. Recent wlanpi-core logs")
    report.append("-" * 80)
    report.append(
        run_command(
            [find_command("journalctl"), "-u", "wlanpi-core", "-n", "50", "--no-pager"]
        )
    )
    report.append("")

    return "\n".join(report)


def main() -> int:
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
        "-p",
        action="store_true",
        help="Upload report to termbin.com and print link",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colorized output messages",
    )

    args = parser.parse_args()

    use_color = not args.no_color

    def log_info(msg):
        if use_color:
            print(f"{BLUE}[*]{NC} {msg}")
        else:
            print(f"[*] {msg}")

    def log_success(msg):
        if use_color:
            print(f"{GREEN}[+]{NC} {msg}")
        else:
            print(f"[+] {msg}")

    def log_error(msg):
        if use_color:
            print(f"{RED}[-]{NC} {msg}")
        else:
            print(f"[-] {msg}")

    log_info("Gathering diagnostics support report (this may take a few seconds)...")
    try:
        report = generate_report()
    except Exception as e:
        log_error(f"Failed to generate report: {e}")
        return 1

    if args.file:
        try:
            path = Path(args.file)
            path.write_text(report)
            log_success(f"Report saved locally to {path.resolve()}")
        except Exception as e:
            log_error(f"Failed to save report to file: {e}")
            return 1

    if args.paste:
        log_info("Uploading report to termbin.com...")
        paste_url = upload_to_termbin(report)
        if paste_url.startswith("https://"):
            log_success("Report uploaded successfully!")
            if use_color:
                print(f"Paste link: {GREEN}{paste_url}{NC}")
            else:
                print(f"Paste link: {paste_url}")
        else:
            log_error(f"Failed to upload report: {paste_url}")
            return 1

    if not args.file and not args.paste:
        print(report)

    return 0


if __name__ == "__main__":
    exit(main())
