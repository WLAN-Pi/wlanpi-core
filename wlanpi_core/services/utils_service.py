import asyncio
import os
import re
import subprocess
import threading
import time
from typing import Optional

from wlanpi_core.constants import BLINKER_FILE, UFW_FILE
from wlanpi_core.core.logging import get_logger

from ..models.runcommand_error import RunCommandError
from ..utils.general import run_command_async, terminate_process
from ..utils.network import get_default_gateways
from ..utils.reachability import parse_targets_param, ping_stats_from_jc, ping_target
from ..utils.speedtest import run_speedtest
from ..utils.validation import validate_interface_name

log = get_logger(__name__)


def _read_dns_servers(path: str = "/etc/resolv.conf") -> list[str]:
    """Read well-formed nameserver entries without leaking a file handle."""
    servers: list[str] = []
    with open(path, encoding="utf-8") as resolv_conf:
        for line in resolv_conf:
            fields = line.split()
            if len(fields) >= 2 and fields[0] == "nameserver":
                servers.append(fields[1])
    return servers


async def _cancel_tasks(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def show_reachability(targets: Optional[list[str]] = None):
    """
    Check if default gateway, internet and DNS are reachable and working.

    Optionally ping additional ``targets`` (hostnames or IPs) in parallel.
    """

    output = {"results": {}}

    # --- Variables ---
    try:
        gateways = await asyncio.to_thread(get_default_gateways)
        if not gateways:
            return {"error": "No default gateway found"}

        dg_interface, default_gateway = list(gateways.items())[0]
        dns_servers = await asyncio.to_thread(_read_dns_servers)
        custom_targets = parse_targets_param(targets)
    except ValueError as err:
        return {"error": str(err)}
    except RunCommandError as err:
        return {"error": "Failed to determine network configuration: {}".format(err)}

    # --- Checks ---
    if not default_gateway:
        return {"error": "No default gateway"}

    ping_google_task = asyncio.create_task(
        run_command_async(
            ["jc", "ping", "-c1", "-W2", "-q", "google.com"],
            raise_on_fail=False,
        )
    )
    browse_google_task = asyncio.create_task(
        run_command_async(
            ["curl", "-s", "-L", "www.google.com"],
            raise_on_fail=False,
            timeout=2,
        )
    )
    ping_gateway_task = asyncio.create_task(
        run_command_async(
            ["jc", "ping", "-c1", "-W2", "-q", default_gateway],
            raise_on_fail=False,
        )
    )
    arping_gateway_task = asyncio.create_task(
        run_command_async(
            ["arping", "-c1", "-w2", "-I", dg_interface, default_gateway],
            raise_on_fail=False,
            timeout=2,
        )
    )
    dns_tasks = [
        asyncio.create_task(
            run_command_async(
                [
                    "dig",
                    "+short",
                    "+time=2",
                    "+tries=1",
                    f"@{dns}",
                    "NS",
                    "google.com",
                ],
                raise_on_fail=False,
            )
        )
        for dns in dns_servers[:3]
    ]
    custom_tasks = [
        asyncio.create_task(ping_target(target)) for target in custom_targets
    ]
    all_tasks = [
        ping_google_task,
        browse_google_task,
        ping_gateway_task,
        arping_gateway_task,
        *dns_tasks,
        *custom_tasks,
    ]

    try:
        ping_google, browse_google, ping_gateway, arping_gateway = await asyncio.gather(
            ping_google_task,
            browse_google_task,
            ping_gateway_task,
            arping_gateway_task,
        )
        dns_results = await asyncio.gather(*dns_tasks)
        custom_results = await asyncio.gather(*custom_tasks)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("Reachability check failed: %r", exc)
        return {"error": "Reachability check failed"}
    finally:
        await _cancel_tasks(all_tasks)

    output["results"]["Ping Google"] = ping_stats_from_jc(
        ping_google.output_from_json() if ping_google.success else None
    )["display"]
    output["results"]["Browse Google"] = (
        "OK"
        if browse_google.success and "google.com" in browse_google.stdout
        else "FAIL"
    )
    output["results"]["Ping Gateway"] = ping_stats_from_jc(
        ping_gateway.output_from_json() if ping_gateway.success else None
    )["display"]

    for index, dns_result in enumerate(dns_results, start=1):
        output["results"][f"DNS Server {index} Resolution"] = (
            "OK" if dns_result.success else "FAIL"
        )

    arping_rtt = re.search(r"\d+(?:\.\d+)?ms", arping_gateway.stdout)
    output["results"]["Arping Gateway"] = arping_rtt.group(0) if arping_rtt else "FAIL"
    output["results"]["custom"] = custom_results

    return output


async def show_speedtest():
    """Run LibreSpeed CLI speedtest and return parsed results."""
    try:
        return {"results": await run_speedtest()}
    except RuntimeError as err:
        return {"error": str(err)}
    except ValueError as err:
        return {"error": str(err)}


async def show_usb():
    """
    Return a list of non-Linux USB interfaces found with the lsusb command
    """
    interfaces = {}

    try:
        lsusb_output = (
            await run_command_async("/usr/bin/lsusb", raise_on_fail=True)
        ).stdout.split("\n")
        lsusb_info = [
            line.split(" ", 6)[-1].strip()
            for line in lsusb_output
            if "Linux" not in line
        ]
    except RunCommandError as err:
        error_descr = "Issue getting usb info using lsusb command"
        interfaces["error"] = {"error": error_descr + ": " + err.error_msg}
        return interfaces

    interfaces["interfaces"] = []

    for result in (result for result in lsusb_info if result != ""):
        interfaces["interfaces"].append(result)

    if not interfaces["interfaces"]:
        interfaces["interfaces"].append("No devices detected")

    return interfaces


def parse_ufw(output):
    """
    Parses the output of the UFW file into readable json for the api.
    """

    lines = output.strip().split("\n")

    status_line = lines[0]
    status = status_line.split(":")[1].strip()

    # Check if there are at least 3 lines (status + headers + at least one rule)
    if len(lines) <= 3:
        # No rules present in the output
        parsed_rules = []
    else:
        rules = lines[3:]
        parsed_rules = []

        # IPv6 pattern detection: "XX (v6)" followed by "ALLOW" and "Anywhere (v6)"
        ipv6_pattern = re.compile(r"\(v6\)")

        for rule in rules:
            parts = rule.split()

            if len(parts) >= 3 and (parts[1] == "ALLOW" or parts[1] == "DENY"):
                to = parts[0]
                action = parts[1]
                from_ = " ".join(parts[2:])
            elif len(parts) >= 4 and ipv6_pattern.search(rule):
                to = " ".join(parts[0:2])
                action = parts[2]
                from_ = " ".join(parts[3:])
            else:
                continue

            parsed_rules.append({"To": to, "Action": action, "From": from_})
    final_output = {"status": status, "ports": parsed_rules}
    return final_output


async def show_ufw():
    """
    Return a list ufw ports
    """
    ufw_file = UFW_FILE
    ufw_info = []

    response = {}

    # check ufw is available
    if not os.path.isfile(ufw_file):
        response["error"] = {"error": "UFW is not installed."}

        return response

    try:
        ufw_output = (
            await run_command_async([ufw_file, "status"], raise_on_fail=True)
        ).stdout
        ufw_info = parse_ufw(ufw_output)

    except Exception as exc:
        log.warning("Unable to read UFW status: %r", exc)
        error_descr = "Issue getting ufw info using ufw command"
        response["error"] = {"error": error_descr}
        return response

    # Add in status line

    response = ufw_info

    return response


_blinker_process: Optional[subprocess.Popen] = None
_blinker_lock = threading.Lock()
_BLINKER_CONTROL_TIMEOUT_SEC = 3
_BLINKER_TERMINATE_GRACE_SEC = 1


def _blinker_script_running() -> bool:
    result = subprocess.run(
        ["pidof", "-x", "portblinker.sh"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_BLINKER_CONTROL_TIMEOUT_SEC,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return False
    return len(result.stdout.strip().split()) > 0


def _signal_unowned_blinker(signal_name: str) -> None:
    subprocess.run(
        ["pkill", f"-{signal_name}", "-f", "portblinker.sh"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=_BLINKER_CONTROL_TIMEOUT_SEC,
    )


def _stop_unowned_blinker() -> None:
    """Stop a blinker inherited from another worker or service instance."""
    _signal_unowned_blinker("TERM")
    deadline = time.monotonic() + _BLINKER_TERMINATE_GRACE_SEC
    while time.monotonic() < deadline:
        if not _blinker_script_running():
            return
        time.sleep(0.1)

    _signal_unowned_blinker("KILL")
    if _blinker_script_running():
        raise RuntimeError("Port blinker did not stop after SIGKILL")


def start_port_blinker(interface: str = "eth0") -> dict:
    """Start the port blinker script (runs until stopped)."""
    global _blinker_process
    interface = validate_interface_name(interface)

    with _blinker_lock:
        if not os.path.isfile(BLINKER_FILE):
            raise FileNotFoundError(f"Port blinker script not found: {BLINKER_FILE}")

        if _blinker_process and _blinker_process.poll() is None:
            return {
                "active": True,
                "status": "already_running",
                "interface": interface,
            }

        if _blinker_script_running():
            return {
                "active": True,
                "status": "already_running",
                "interface": interface,
            }

        cmd = [BLINKER_FILE, "-i", interface, "--no-color"]
        _blinker_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"active": True, "status": "started", "interface": interface}


def stop_port_blinker() -> dict:
    """Stop a running port blinker process."""
    global _blinker_process
    with _blinker_lock:
        stopped = False

        if _blinker_process and _blinker_process.poll() is None:
            terminate_process(_blinker_process)
            stopped = True
        _blinker_process = None

        if _blinker_script_running():
            _stop_unowned_blinker()
            stopped = True

        return {"active": False, "status": "stopped" if stopped else "not_running"}


def port_blinker_status() -> dict:
    """Return whether the port blinker script is running."""
    global _blinker_process
    with _blinker_lock:
        active = _blinker_script_running()
        if not active and _blinker_process and _blinker_process.poll() is not None:
            _blinker_process.wait()
            _blinker_process = None
        return {"active": active}
