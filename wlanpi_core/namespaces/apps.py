"""
Application lifecycle management within network namespaces.

This module provides functions for starting, stopping, and managing applications
that run within network namespaces.
"""

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wlanpi_core.constants import APPS_FILE, PID_DIR
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.namespaces import processes
from wlanpi_core.utils.general import run_command, terminate_process
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


@dataclass
class _OwnedAppProcess:
    process: subprocess.Popen[Any]
    namespace: str | None
    app_id: str


_owned_app_processes: dict[int, _OwnedAppProcess] = {}
_owned_app_processes_lock = threading.Lock()


def _prune_owned_app_processes() -> None:
    with _owned_app_processes_lock:
        stopped_pids = [
            pid
            for pid, owned in _owned_app_processes.items()
            if owned.process.poll() is not None
        ]
        for pid in stopped_pids:
            _owned_app_processes.pop(pid, None)


def _owned_app_running(namespace: str | None) -> bool:
    _prune_owned_app_processes()
    with _owned_app_processes_lock:
        return any(
            owned.namespace == namespace for owned in _owned_app_processes.values()
        )


def _stop_owned_app(pid: int | None, namespace: str | None, app_id: str) -> bool | None:
    """Stop and reap an app launched by this service process, if known."""
    if not pid:
        return None

    with _owned_app_processes_lock:
        owned = _owned_app_processes.get(pid)

    if owned is None:
        return None
    if owned.namespace != namespace or (app_id and owned.app_id != app_id):
        log.error("App PID file does not match the locally owned process")
        return False
    if owned.process.poll() is not None:
        with _owned_app_processes_lock:
            _owned_app_processes.pop(pid, None)
        return False

    with _owned_app_processes_lock:
        _owned_app_processes.pop(pid, None)
    try:
        terminate_process(owned.process)
    except BaseException:
        with _owned_app_processes_lock:
            _owned_app_processes[pid] = owned
        raise
    return True


def _recorded_app_running(pid_file: Path) -> bool:
    """Fail closed when a PID file still refers to a live process."""
    if not pid_file.exists():
        return False

    try:
        pid_data = json.loads(pid_file.read_text())
        pid = int(pid_data["pid"] if isinstance(pid_data, dict) else pid_data)
        if pid <= 0:
            raise ValueError("PID must be positive")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid app PID file {pid_file}: {error}") from error

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        return False
    except PermissionError:
        return True
    app_command = pid_data.get("app_command", "") if isinstance(pid_data, dict) else ""
    if app_command and not _is_recorded_app(pid, app_command):
        # The PID was reused (reboot, service restart): the app is not running.
        pid_file.unlink(missing_ok=True)
        return False
    return True


def get_app_command(app_id: str) -> str | None:
    """
    Get the command for an app ID from the apps file.

    Args:
        app_id: Application identifier

    Returns:
        Command string if found, None otherwise

    Raises:
        FileNotFoundError: If apps file doesn't exist and can't be created
        json.JSONDecodeError: If apps file is malformed

    Examples:
        >>> command = get_app_command("my_app")
        >>> if command:
        ...     print(f"App command: {command}")
    """
    apps_file = Path(APPS_FILE)
    if not apps_file.exists():
        if not apps_file.parent.exists():
            raise FileNotFoundError(
                f"Apps file parent directory does not exist: {apps_file.parent}. "
                "Cannot create apps file (e.g. in CI /home/wlanpi may be missing)."
            )
        apps_file.touch()

    try:
        with apps_file.open("r") as f:
            apps = json.load(f)
        return apps.get(app_id)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse apps file {APPS_FILE}: {e}")
        raise


def start_app_in_namespace(
    namespace: str | None,
    app_id: str,
    pid_dir: Path | None = None,
) -> bool:
    """
    Start an application in a network namespace or root namespace.

    Args:
        namespace: Network namespace name, or None for root
        app_id: Application identifier from apps file
        pid_dir: Directory for PID files (defaults to PID_DIR constant)

    Returns:
        True if app was started successfully, False otherwise

    Raises:
        FileNotFoundError: If apps file doesn't exist
        json.JSONDecodeError: If apps file is malformed
        ValueError: If app_id not found in apps file

    Examples:
        >>> start_app_in_namespace("test_ns", "my_app")
    """
    # Resolve app first so we don't touch the filesystem (e.g. mkdir) when app not found
    app_command = get_app_command(app_id)
    if not app_command:
        log.error(f"App ID {app_id} not found in apps file.")
        raise ValueError(f"App ID {app_id} not found in apps file")

    if pid_dir is None:
        pid_dir = Path(PID_DIR)
    pid_dir.mkdir(parents=True, exist_ok=True)

    if _owned_app_running(namespace):
        log.warning(
            "An application is already running in namespace '%s'",
            namespace if namespace else "root",
        )
        return False

    namespace_display = namespace if namespace else "root"
    log.info(
        f"Starting app '{app_id}' in namespace '{namespace_display}' with command: {app_command}"
    )

    # Build command based on namespace
    if namespace is None:  # Root namespace
        cmd = app_command.split()
        pid_file = pid_dir / "root.pid"
    else:
        cmd = ["ip", "netns", "exec", namespace, *app_command.split()]
        pid_file = pid_dir / f"{namespace}.pid"

    if _recorded_app_running(pid_file):
        log.warning("A recorded application process is still running")
        return False

    # Log the full command being executed
    log.info(f"Executing command: {' '.join(cmd)}")
    log.info(f"App log file will be written to: /tmp/{app_id}.log")

    # Clear/create log file
    log_file_path = Path(f"/tmp/{app_id}.log")
    with log_file_path.open("w"):
        pass

    # Start the process
    with log_file_path.open("w") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )

    with _owned_app_processes_lock:
        _owned_app_processes[proc.pid] = _OwnedAppProcess(proc, namespace, app_id)

    # Store both PID and app_command for reliable cleanup
    pid_data = {"pid": proc.pid, "app_id": app_id, "app_command": app_command}
    try:
        pid_file.write_text(json.dumps(pid_data))
    except BaseException:
        with _owned_app_processes_lock:
            _owned_app_processes.pop(proc.pid, None)
        terminate_process(proc)
        raise

    log.info(
        f"Launched app '{app_id}' in namespace '{namespace_display}' with PID {proc.pid}"
    )

    # Wait a moment for process to start
    time.sleep(0.5)

    # Verify process is running
    try:
        if proc.poll() is None:
            log.info(f"Process {proc.pid} is running (confirmed via poll())")
        else:
            returncode = proc.poll()
            log.warning(
                f"Process {proc.pid} exited immediately with return code {returncode}"
            )
            with _owned_app_processes_lock:
                _owned_app_processes.pop(proc.pid, None)
            # Try to read some log output for diagnosis
            if log_file_path.exists():
                try:
                    log_content = log_file_path.read_text()[:500]
                    if log_content:
                        log.warning(f"Process log output: {log_content}")
                except OSError:
                    pass
            return False
    except Exception as e:
        log.warning(f"Could not verify process status: {e}")

    # For namespaced apps, verify it's visible in the namespace
    if namespace is not None:
        _verify_app_in_namespace(proc.pid, namespace, app_command)

    log.info(
        f"App '{app_id}' startup verification complete. Monitor logs at /tmp/{app_id}.log"
    )
    return True


def _verify_app_in_namespace(pid: int, namespace: str, app_command: str) -> None:
    """
    Verify that an app process is visible in a namespace.

    Args:
        pid: Process ID
        namespace: Namespace name
        app_command: App command for matching
    """
    try:
        ns_pids = processes.get_processes_in_namespace(namespace)
        if pid in ns_pids:
            log.info(
                f"Process {pid} confirmed visible in namespace '{namespace}' (found in namespace PIDs)"
            )
        else:
            log.info(
                f"Process {pid} not directly in namespace PIDs list (may be wrapper process). "
                f"Namespace PIDs: {ns_pids}"
            )
            # Try to find the actual app process in the namespace
            try:
                cmd_parts = app_command.split()
                if cmd_parts:
                    base_cmd = cmd_parts[0]
                    ps_result = ns_exec(
                        ["ps", "aux"], namespace=namespace, no_output=True
                    )
                    matching_lines = [
                        line
                        for line in ps_result.stdout.splitlines()
                        if base_cmd in line
                    ]
                    if matching_lines:
                        log.info(
                            f"Found {len(matching_lines)} process(es) matching '{base_cmd}' in namespace '{namespace}'"
                        )
                        for line in matching_lines[:3]:
                            log.debug(f"  {line.strip()}")
            except Exception as e:
                log.debug(f"Could not check for app process in namespace: {e}")
    except Exception as e:
        log.warning(f"Could not verify process in namespace '{namespace}': {e}")


def stop_app_in_namespace(
    namespace: str | None,
    pid_dir: Path | None = None,
) -> bool:
    """
    Stop an application running in a network namespace or root namespace.

    Args:
        namespace: Network namespace name, or None for root
        pid_dir: Directory for PID files (defaults to PID_DIR constant)

    Returns:
        True if app was stopped successfully, False if no app was running

    Examples:
        >>> stop_app_in_namespace("test_ns")
    """
    if pid_dir is None:
        pid_dir = Path(PID_DIR)

    # Handle PID file naming for root namespace
    if namespace is None:
        pid_file = pid_dir / "root.pid"
        namespace_display = "root"
    else:
        pid_file = pid_dir / f"{namespace}.pid"
        namespace_display = namespace

    if not pid_file.exists():
        log.warning(f"No PID file found for namespace {namespace_display}.")
        return False

    try:
        pid_data_str = pid_file.read_text().strip()
        try:
            # Try to parse as JSON (new format with app_command)
            pid_data = json.loads(pid_data_str)
            pid = pid_data.get("pid")
            app_command = pid_data.get("app_command", "")
            app_id = pid_data.get("app_id", "")
        except (json.JSONDecodeError, ValueError, TypeError):
            # Fall back to old format (just PID number)
            try:
                pid = int(pid_data_str)
            except ValueError:
                log.error(f"Invalid PID file format: {pid_data_str}")
                pid_file.unlink(missing_ok=True)
                return False
            app_command = ""
            app_id = ""

        if namespace is None:
            owned_result = _stop_owned_app(pid, None, app_id)
            if owned_result is not None:
                stopped = owned_result
            else:
                # Root namespace: use simpler approach
                stopped = _stop_app_in_root(pid, app_command, namespace_display)
        else:
            owned_result = _stop_owned_app(pid, namespace, app_id)
            if owned_result is not None:
                stopped = owned_result
            else:
                # Namespace operations: use namespace-aware process management
                stopped = _stop_app_in_namespace_safe(
                    namespace, pid, app_command, app_id
                )

        if stopped:
            pid_file.unlink(missing_ok=True)
        return stopped

    except Exception as e:
        log.error(f"Failed to stop app in {namespace_display}: {e}", exc_info=True)
        return False


def _is_recorded_app(pid: int, app_command: str) -> bool:
    """Return whether `pid` still runs `app_command` as Core started it.

    App pidfiles outlive reboots and service restarts, so a PID may now
    belong to something else. The argv must end with the recorded command,
    the program compared by basename, so a script started through PATH and
    its shebang (python3 /usr/bin/orb --serve) matches.
    """
    parts = app_command.split()
    if not parts:
        return False
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    argv = [arg.decode(errors="replace") for arg in raw.split(b"\0") if arg]
    tail = argv[-len(parts) :]
    return (
        len(tail) == len(parts)
        and tail[1:] == parts[1:]
        and os.path.basename(tail[0]) == os.path.basename(parts[0])
    )


def _stop_app_in_root(
    pid: int | None, app_command: str, namespace_display: str
) -> bool:
    """Stop app in root namespace."""
    try:
        if pid:
            if not _is_recorded_app(pid, app_command):
                log.info(f"PID {pid} is not the recorded app; dropping its pidfile")
                return True
            run_command(["kill", str(pid)], raise_on_fail=True)
            log.info(f"Stopped app in {namespace_display} with PID {pid}")
            return True
        elif app_command:
            # Extract the base command (first part) for matching
            cmd_parts = app_command.split()
            if cmd_parts:
                base_cmd = cmd_parts[0]
                run_command(["pkill", "-f", base_cmd], raise_on_fail=True)
                log.info(
                    f"Stopped app in {namespace_display} using pkill for {base_cmd}"
                )
                return True
    except RunCommandError as e:
        log.warning(f"Failed to kill app in {namespace_display}: {e}")
    return False


def _stop_app_in_namespace_safe(
    namespace: str,
    pid: int | None,
    app_command: str,
    app_id: str,
) -> bool:
    """Stop app in namespace with safety checks."""
    from wlanpi_core.namespaces.namespace import namespace_exists

    # Step 1: Verify namespace exists
    try:
        if not namespace_exists(namespace):
            log.warning(f"Namespace {namespace} does not exist, skipping app stop")
            return False
    except Exception as e:
        log.warning(f"Could not verify namespace exists: {e}")
        return False

    # Step 2: Verify PID from file is actually in this namespace
    verified_pid = None
    if pid:
        try:
            identify_result = run_command(
                ["ip", "netns", "identify", str(pid)], raise_on_fail=False
            )
            if identify_result.return_code == 0 and namespace in identify_result.stdout:
                verified_pid = pid
                log.info(f"PID {pid} confirmed in namespace {namespace}")
            else:
                log.warning(
                    f"PID {pid} is not in namespace {namespace} "
                    f"(found in: {identify_result.stdout.strip() or 'unknown'}), "
                    f"will search namespace for matching processes"
                )
        except RunCommandError as e:
            log.debug(f"Could not identify namespace for PID {pid}: {e}")

    # Step 3: Get all PIDs in the namespace
    try:
        ns_pids = processes.get_processes_in_namespace(namespace)

        if not ns_pids:
            # Nothing runs there, so the app is not running: the pidfile is stale.
            log.info(f"No processes found in namespace {namespace}")
            return True

        log.debug(f"Found {len(ns_pids)} process(es) in namespace {namespace}")

        # Step 4: only processes in the namespace still running the recorded
        # command (a PID from the file may have been reused, #304).
        matching_pids = [
            ns_pid for ns_pid in ns_pids if _is_recorded_app(ns_pid, app_command)
        ]

        # Step 5: Kill only the matching PIDs that are confirmed in namespace
        if matching_pids:
            killed_count = 0
            for match_pid in matching_pids:
                try:
                    run_command(["kill", str(match_pid)], raise_on_fail=True)
                    killed_count += 1
                    log.info(
                        f"Killed PID {match_pid} (app '{app_id}') in namespace {namespace}"
                    )
                except RunCommandError as e:
                    log.warning(
                        f"Failed to kill PID {match_pid} in namespace {namespace}: {e}"
                    )

            if killed_count > 0:
                log.info(
                    f"Successfully stopped {killed_count} process(es) in namespace {namespace}"
                )
                return True
        else:
            # The app is not running: drop the stale pidfile so a reused PID
            # never blocks the next start.
            log.info(
                f"No matching processes found in namespace {namespace} "
                f"(checked {len(ns_pids)} process(es))"
            )
            return True

    except RunCommandError as e:
        log.error(f"Failed to get PIDs from namespace {namespace}: {e}")
        # Fallback: if we have a verified PID, try to kill it directly
        if verified_pid and _is_recorded_app(verified_pid, app_command):
            try:
                run_command(["kill", str(verified_pid)], raise_on_fail=True)
                log.info(
                    f"Killed verified PID {verified_pid} in namespace {namespace} (fallback)"
                )
                return True
            except RunCommandError as kill_err:
                log.warning(
                    f"Fallback kill also failed for PID {verified_pid}: {kill_err}"
                )
    except Exception as e:
        log.error(f"Unexpected error getting PIDs from namespace {namespace}: {e}")

    return False
