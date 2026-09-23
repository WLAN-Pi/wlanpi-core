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
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)

# Directory name for the root namespace; `@` cannot appear in a netns name.
_ROOT_DIR_NAME = "@root"


# Root keeps the conventional control directory so plain `wpa_cli` works.
ROOT_CTRL_DIR = "/run/wpa_supplicant"


def runtime_dir(namespace: str | None) -> Path:
    """Return Core's runtime directory for supplicants in `namespace`."""
    return Path(RUN_DIR) / "wpa_supplicant" / (namespace or _ROOT_DIR_NAME)


def pidfile_path(iface: str, namespace: str | None) -> Path:
    """Return the pidfile Core uses for the supplicant on (namespace, iface)."""
    return runtime_dir(namespace) / f"{iface}.pid"


def config_path(iface: str, namespace: str | None) -> Path:
    """Return the wpa_supplicant config Core writes for (namespace, iface)."""
    return runtime_dir(namespace) / f"{iface}.conf"


def log_path(iface: str, namespace: str | None) -> Path:
    """Return the wpa_supplicant log for (namespace, iface)."""
    return runtime_dir(namespace) / f"{iface}.log"


def ctrl_dir(namespace: str | None) -> str:
    """Return the control socket directory for supplicants Core runs in `namespace`.

    /run is shared by every netns, so namespaced supplicants get their own
    directory; otherwise wlan1 in two namespaces would share one socket.
    """
    if namespace is None:
        return ROOT_CTRL_DIR
    return str(runtime_dir(namespace) / "ctrl")


def wpa_cli_command(iface: str, namespace: str | None, *args: str) -> list[str]:
    """Build a wpa_cli command for (namespace, iface).

    Uses Core's control directory when Core's supplicant owns the interface,
    and the default directory otherwise (a supplicant started by another tool).
    """
    ctrl = ctrl_dir(namespace)
    if namespace is not None and not (Path(ctrl) / iface).exists():
        ctrl = ROOT_CTRL_DIR
    return ["wpa_cli", "-p", ctrl, "-i", iface, *args]


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


def _terminate(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(20):
        if not _read_cmdline(pid):
            return
        time.sleep(0.1)
    log.warning(f"wpa_supplicant {pid} did not exit after SIGTERM")


def _stop_pidfile(path: Path) -> None:
    iface = path.stem
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        pid = None
    # Guard against PID reuse: only signal a supplicant for this iface.
    if pid is not None and _supplicant_iface(_read_cmdline(pid)) == iface:
        log.info(f"Stopping wpa_supplicant {pid} for {iface}")
        _terminate(pid)
    path.unlink(missing_ok=True)


def stop_supplicant(iface: str, namespace: str | None) -> None:
    """
    Stop the wpa_supplicant Core started for (namespace, iface), if any.

    Only the process named in Core's pidfile is signalled, and only if it is
    still a wpa_supplicant for `iface`; nothing else on the host is touched.
    """
    _stop_pidfile(pidfile_path(iface, namespace))


def stop_namespace_supplicants(namespace: str) -> None:
    """Stop every wpa_supplicant Core started in `namespace`."""
    for path in sorted(pidfile_path("x", namespace).parent.glob("*.pid")):
        _stop_pidfile(path)


def start_or_restart_supplicant(iface: str, namespace: str | None) -> None:
    """
    Start or restart wpa_supplicant for an interface.

    The config must already be written to config_path(iface, namespace). The
    pidfile, log, and control socket are all keyed by (namespace, iface).

    Args:
        iface: Interface name
        namespace: Network namespace name, or None for root

    Raises:
        RunCommandError: If wpa_supplicant fails to start

    Examples:
        >>> start_or_restart_supplicant("wlan0", "test_ns")
    """
    namespace_display = namespace if namespace else "root"
    log.info(
        f"Starting/restarting wpa_supplicant for {iface} in namespace {namespace_display}"
    )

    # Stop the supplicant Core previously started for this (namespace, iface)
    stop_supplicant(iface, namespace)

    # Remove a stale control socket left by a supplicant that died
    (Path(ctrl_dir(namespace)) / iface).unlink(missing_ok=True)

    runtime_dir(namespace).mkdir(mode=0o700, parents=True, exist_ok=True)
    log_file = log_path(iface, namespace)
    log_file.unlink(missing_ok=True)
    log_file.touch()

    # Start wpa_supplicant, recording its PID for targeted teardown
    ns_exec(
        [
            "wpa_supplicant",
            "-B",
            "-i",
            iface,
            "-c",
            str(config_path(iface, namespace)),
            "-D",
            "nl80211",
            "-f",
            str(log_file),
            "-t",
            "-P",
            str(pidfile_path(iface, namespace)),
        ],
        namespace=namespace,
    )

    log.info(f"wpa_supplicant started for {iface} in namespace {namespace_display}")


def parse_wpa_log(iface: str, namespace: str | None = None, timeout: int = 30) -> None:
    """
    Parse wpa_supplicant log file waiting for connection completion.

    Args:
        iface: Interface name
        namespace: Network namespace name, or None for root
        timeout: Maximum time to wait in seconds

    Raises:
        TimeoutError: If connection doesn't complete within timeout

    Examples:
        >>> parse_wpa_log("wlan0", timeout=30)
    """
    start_time = time.time()
    log_file = log_path(iface, namespace)

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
