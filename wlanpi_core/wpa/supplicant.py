"""
WPA supplicant process management.

This module provides functions for starting, stopping, and managing
wpa_supplicant processes.
"""
import logging
import time
from pathlib import Path
from typing import Optional

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def start_or_restart_supplicant(
    iface: str,
    namespace: Optional[str],
    config_path: Path,
    ctrl_interface: str = "/run/wpa_supplicant",
) -> None:
    """
    Start or restart wpa_supplicant for an interface.

    Args:
        iface: Interface name
        namespace: Network namespace name, or None for root
        config_path: Path to wpa_supplicant configuration file
        ctrl_interface: Control interface directory

    Raises:
        RunCommandError: If wpa_supplicant fails to start

    Examples:
        >>> start_or_restart_supplicant("wlan0", "test_ns", Path("/etc/wpa_supplicant/wlan0.conf"))
    """
    namespace_display = namespace if namespace else "root"
    log.info(f"Starting/restarting wpa_supplicant for {iface} in namespace {namespace_display}")

    # Kill any existing wpa_supplicant for this interface
    try:
        ns_exec(["pkill", "-f", f"wpa_supplicant -B -i {iface}"], namespace=namespace)
    except RunCommandError:
        pass  # May not exist, that's okay

    # Remove control interface socket
    try:
        ns_exec(["rm", "-f", f"{ctrl_interface}/{iface}"], namespace=namespace)
    except RunCommandError:
        pass  # May not exist, that's okay

    # Prepare log file
    log_file = Path(f"/tmp/wpa-{iface}.log")
    if log_file.exists():
        log_file.unlink()
    log_file.touch()

    # Start wpa_supplicant
    ns_exec(
        [
            "wpa_supplicant",
            "-B",
            "-i",
            iface,
            "-c",
            str(config_path),
            "-D",
            "nl80211",
            "-f",
            f"/tmp/wpa-{iface}.log",
            "-t",
        ],
        namespace=namespace,
    )

    log.info(f"wpa_supplicant started for {iface} in namespace {namespace_display}")


def parse_wpa_log(iface: str, timeout: int = 30) -> None:
    """
    Parse wpa_supplicant log file waiting for connection completion.

    Args:
        iface: Interface name
        timeout: Maximum time to wait in seconds

    Raises:
        TimeoutError: If connection doesn't complete within timeout

    Examples:
        >>> parse_wpa_log("wlan0", timeout=30)
    """
    start_time = time.time()
    log_file = Path(f"/tmp/wpa-{iface}.log")

    if not log_file.exists():
        log.warning(f"WPA log file {log_file} does not exist")
        return

    with log_file.open("r") as f:
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                if time.time() - start_time > timeout:
                    raise TimeoutError("Timeout waiting for connection to complete")
                continue

            line = line.strip()

            # Extract timestamp if present
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[0].replace(".", "", 1).isdigit():
                epoch = float(parts[0])
                log_msg = parts[1].strip()
            else:
                log_msg = line

            log.debug(f"WPA log: {log_msg}")

            if "CTRL-EVENT-CONNECTED" in line and "completed" in line:
                log.info(f"Connection completed for {iface}")
                break


def kill_all_supplicants() -> None:
    """
    Stop any running wpa_supplicant processes across all namespaces.

    This is a best-effort operation and will not raise exceptions.

    Examples:
        >>> kill_all_supplicants()
    """
    try:
        from wlanpi_core.utils.general import run_command
        run_command(["sudo", "pkill", "-f", "wpa_supplicant"], raise_on_fail=False)
        log.info("Killed all wpa_supplicant processes")
    except Exception as e:
        log.warning(f"Failed to kill all wpa_supplicants: {e}")
