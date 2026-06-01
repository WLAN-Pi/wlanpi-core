"""
Application lifecycle management within network namespaces.

This module provides functions for starting, stopping, and managing applications
that run within network namespaces.
"""
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

from wlanpi_core.constants import APPS_FILE, PID_DIR
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.namespaces import processes
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def get_app_command(app_id: str) -> Optional[str]:
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
    namespace: Optional[str],
    app_id: str,
    pid_dir: Optional[Path] = None,
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

    namespace_display = namespace if namespace else "root"
    log.info(f"Starting app '{app_id}' in namespace '{namespace_display}' with command: {app_command}")

    # Build command based on namespace
    if namespace is None:  # Root namespace
        cmd = app_command.split()
        pid_file = pid_dir / "root.pid"
    else:
        cmd = ["ip", "netns", "exec", namespace] + app_command.split()
        pid_file = pid_dir / f"{namespace}.pid"

    # Log the full command being executed
    log.info(f"Executing command: {' '.join(cmd)}")
    log.info(f"App log file will be written to: /tmp/{app_id}.log")

    # Clear/create log file
    log_file_path = Path(f"/tmp/{app_id}.log")
    with log_file_path.open("w"):
        pass

    # Start the process
    with log_file_path.open("w") as log_file:
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file)

    # Store both PID and app_command for reliable cleanup
    pid_data = {"pid": proc.pid, "app_id": app_id, "app_command": app_command}
    pid_file.write_text(json.dumps(pid_data))

    log.info(f"Launched app '{app_id}' in namespace '{namespace_display}' with PID {proc.pid}")

    # Wait a moment for process to start
    time.sleep(0.5)

    # Verify process is running
    try:
        if proc.poll() is None:
            log.info(f"Process {proc.pid} is running (confirmed via poll())")
        else:
            returncode = proc.poll()
            log.warning(f"Process {proc.pid} exited immediately with return code {returncode}")
            # Try to read some log output for diagnosis
            if log_file_path.exists():
                try:
                    log_content = log_file_path.read_text()[:500]
                    if log_content:
                        log.warning(f"Process log output: {log_content}")
                except Exception:
                    pass
            return False
    except Exception as e:
        log.warning(f"Could not verify process status: {e}")

    # For namespaced apps, verify it's visible in the namespace
    if namespace is not None:
        _verify_app_in_namespace(proc.pid, namespace, app_command)

    log.info(f"App '{app_id}' startup verification complete. Monitor logs at /tmp/{app_id}.log")
    return True


def _verify_app_in_namespace(pid: int, namespace: str, app_command: str):
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
            log.info(f"Process {pid} confirmed visible in namespace '{namespace}' (found in namespace PIDs)")
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
                    ps_result = ns_exec(["ps", "aux"], namespace=namespace, no_output=True)
                    matching_lines = [line for line in ps_result.stdout.splitlines() if base_cmd in line]
                    if matching_lines:
                        log.info(f"Found {len(matching_lines)} process(es) matching '{base_cmd}' in namespace '{namespace}'")
                        for line in matching_lines[:3]:
                            log.debug(f"  {line.strip()}")
            except Exception as e:
                log.debug(f"Could not check for app process in namespace: {e}")
    except Exception as e:
        log.warning(f"Could not verify process in namespace '{namespace}': {e}")


def stop_app_in_namespace(
    namespace: Optional[str],
    pid_dir: Optional[Path] = None,
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
            # Root namespace: use simpler approach
            return _stop_app_in_root(pid, app_command, namespace_display)
        else:
            # Namespace operations: use namespace-aware process management
            return _stop_app_in_namespace_safe(namespace, pid, app_command, app_id)

    except Exception as e:
        log.error(f"Failed to stop app in {namespace_display}: {e}", exc_info=True)
        return False
    finally:
        pid_file.unlink(missing_ok=True)


def _stop_app_in_root(pid: Optional[int], app_command: str, namespace_display: str) -> bool:
    """Stop app in root namespace."""
    try:
        if pid:
            run_command(["kill", str(pid)], raise_on_fail=True)
            log.info(f"Stopped app in {namespace_display} with PID {pid}")
            return True
        elif app_command:
            # Extract the base command (first part) for matching
            cmd_parts = app_command.split()
            if cmd_parts:
                base_cmd = cmd_parts[0]
                run_command(["pkill", "-f", base_cmd], raise_on_fail=True)
                log.info(f"Stopped app in {namespace_display} using pkill for {base_cmd}")
                return True
    except RunCommandError as e:
        log.warning(f"Failed to kill app in {namespace_display}: {e}")
    return False


def _stop_app_in_namespace_safe(
    namespace: str,
    pid: Optional[int],
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
            identify_result = run_command(["ip", "netns", "identify", str(pid)], raise_on_fail=False)
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
            log.info(f"No processes found in namespace {namespace}")
            return False

        log.debug(f"Found {len(ns_pids)} process(es) in namespace {namespace}")

        # Step 4: Find matching PIDs by checking command lines
        matching_pids = []
        if app_command:
            cmd_parts = app_command.split()
            base_cmd = cmd_parts[0] if cmd_parts else ""

            # Also check if verified_pid is in the namespace PIDs list
            if verified_pid and verified_pid in ns_pids:
                matching_pids.append(verified_pid)
                log.info(f"PID {verified_pid} from file is in namespace and matches app")

            # Check other PIDs in namespace for command match
            for ns_pid in ns_pids:
                if ns_pid == verified_pid:
                    continue  # Already added

                try:
                    # Check /proc/<pid>/cmdline to see if it matches our app
                    cmdline_result = run_command(
                        ["cat", f"/proc/{ns_pid}/cmdline"], raise_on_fail=False, no_output=True
                    )
                    if cmdline_result.return_code == 0:
                        cmdline = cmdline_result.stdout.replace('\0', ' ')
                        if base_cmd in cmdline:
                            matching_pids.append(ns_pid)
                            log.debug(f"Found matching PID {ns_pid} in namespace: {cmdline.strip()}")
                except RunCommandError:
                    # Process may have exited, skip it
                    continue
        elif verified_pid and verified_pid in ns_pids:
            # No app_command but we have a verified PID in namespace
            matching_pids.append(verified_pid)

        # Step 5: Kill only the matching PIDs that are confirmed in namespace
        if matching_pids:
            killed_count = 0
            for match_pid in matching_pids:
                try:
                    run_command(["kill", str(match_pid)], raise_on_fail=True)
                    killed_count += 1
                    log.info(f"Killed PID {match_pid} (app '{app_id}') in namespace {namespace}")
                except RunCommandError as e:
                    log.warning(f"Failed to kill PID {match_pid} in namespace {namespace}: {e}")

            if killed_count > 0:
                log.info(f"Successfully stopped {killed_count} process(es) in namespace {namespace}")
                return True
        else:
            log.info(
                f"No matching processes found in namespace {namespace} "
                f"(checked {len(ns_pids)} process(es))"
            )

    except RunCommandError as e:
        log.error(f"Failed to get PIDs from namespace {namespace}: {e}")
        # Fallback: if we have a verified PID, try to kill it directly
        if verified_pid:
            try:
                run_command(["kill", str(verified_pid)], raise_on_fail=True)
                log.info(f"Killed verified PID {verified_pid} in namespace {namespace} (fallback)")
                return True
            except RunCommandError as kill_err:
                log.warning(f"Fallback kill also failed for PID {verified_pid}: {kill_err}")
    except Exception as e:
        log.error(f"Unexpected error getting PIDs from namespace {namespace}: {e}")

    return False
