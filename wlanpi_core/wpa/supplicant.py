"""
WPA supplicant process management.

This module provides functions for starting, stopping, and managing
wpa_supplicant processes.
"""

import logging
import os
import signal
import time
from pathlib import Path

from wlanpi_core.constants import RUN_DIR
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)

# Directory name for the root namespace; `@` cannot appear in a netns name.
_ROOT_DIR_NAME = "@root"


def pidfile_path(iface: str, namespace: str | None) -> Path:
    """Return the pidfile Core uses for the supplicant on (namespace, iface)."""
    return (
        Path(RUN_DIR)
        / "wpa_supplicant"
        / (namespace or _ROOT_DIR_NAME)
        / f"{iface}.pid"
    )


def _read_cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [arg.decode(errors="replace") for arg in raw.split(b"\0") if arg]


def _proc_pids() -> list[int]:
    return [int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit()]


def _supplicant_iface(argv: list[str]) -> str | None:
    """Return the -i argument if argv is a wpa_supplicant command line."""
    if not argv or not argv[0].endswith("wpa_supplicant") or "-i" not in argv:
        return None
    index = argv.index("-i") + 1
    return argv[index] if index < len(argv) else None


def _wait_gone(pid: int, seconds: float) -> bool:
    for _ in range(int(seconds * 10)):
        if not _read_cmdline(pid):
            return True
        time.sleep(0.1)
    return not _read_cmdline(pid)


def _terminate(pid: int) -> bool:
    """SIGTERM, then SIGKILL after a 2 s grace; return whether the PID is gone."""
    for sig, grace in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 1.0)):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return True
        if _wait_gone(pid, grace):
            return True
        log.warning(f"wpa_supplicant {pid} still running after {sig.name}")
    return False


def _is_core_supplicant(argv: list[str], path: Path) -> bool:
    """Return whether argv is the supplicant Core started with this pidfile.

    Checking `-P <path>` as well as `-i` guards against PID reuse by another
    supplicant for the same interface name, such as Core's own in another
    namespace.
    """
    if _supplicant_iface(argv) != path.stem or "-P" not in argv:
        return False
    index = argv.index("-P") + 1
    return index < len(argv) and argv[index] == str(path)


def _stop_pidfile(path: Path) -> bool:
    """Stop the supplicant named in `path`; return False if it survived."""
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        pid = None
    if pid is not None and _is_core_supplicant(_read_cmdline(pid), path):
        log.info(f"Stopping wpa_supplicant {pid} for {path.stem}")
        if not _terminate(pid):
            log.error(f"Could not stop wpa_supplicant {pid}; keeping {path}")
            return False
    path.unlink(missing_ok=True)
    return True


def stop_supplicant(iface: str, namespace: str | None) -> bool:
    """
    Stop the wpa_supplicant Core started for (namespace, iface), if any.

    Only the process named in Core's pidfile is signalled, and only if it is
    still the wpa_supplicant Core started with that pidfile; nothing else on
    the host is touched. Returns False if the process would not die.
    """
    return _stop_pidfile(pidfile_path(iface, namespace))


def stop_namespace_supplicants(namespace: str) -> None:
    """Stop every wpa_supplicant Core started in `namespace`."""
    for path in sorted(pidfile_path("x", namespace).parent.glob("*.pid")):
        _stop_pidfile(path)


def start_or_restart_supplicant(
    iface: str,
    namespace: str | None,
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
    log.info(
        f"Starting/restarting wpa_supplicant for {iface} in namespace {namespace_display}"
    )

    # Stop the supplicant Core previously started for this (namespace, iface);
    # never start a second one beside a supplicant that would not die.
    if not stop_supplicant(iface, namespace):
        raise RunCommandError(
            f"wpa_supplicant for {iface} in {namespace_display} did not stop", 1
        )

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

    # Start wpa_supplicant, recording its PID for targeted teardown
    pidfile = pidfile_path(iface, namespace)
    pidfile.parent.mkdir(parents=True, exist_ok=True)
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
            "-P",
            str(pidfile),
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
                float(parts[0])
                log_msg = parts[1].strip()
            else:
                log_msg = line

            log.debug(f"WPA log: {log_msg}")

            if "CTRL-EVENT-CONNECTED" in line and "completed" in line:
                log.info(f"Connection completed for {iface}")
                break


def kill_all_supplicants() -> None:
    """
    Stop every wpa_supplicant Core started, in every namespace.

    Uses Core's pidfiles, then sweeps supplicants started by Core before
    pidfiles existed (recognised by Core's `-f /tmp/wpa-<iface>.log`
    argument). System supplicants, such as NetworkManager's, are left alone.
    Best effort; does not raise.
    """
    try:
        for path in sorted((Path(RUN_DIR) / "wpa_supplicant").glob("*/*.pid")):
            _stop_pidfile(path)
        for pid in _proc_pids():
            argv = _read_cmdline(pid)
            iface = _supplicant_iface(argv)
            if iface is None or "-f" not in argv:
                continue
            log_index = argv.index("-f") + 1
            if log_index < len(argv) and argv[log_index] == f"/tmp/wpa-{iface}.log":
                log.info(f"Stopping legacy Core wpa_supplicant {pid} for {iface}")
                _terminate(pid)
    except Exception as e:
        log.warning(f"Failed to stop Core wpa_supplicants: {e}")
