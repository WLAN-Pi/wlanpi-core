"""List, inspect, and signal processes in network namespaces."""

import logging
from typing import Any

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def get_processes_in_namespace(namespace: str) -> list[int]:
    """Return the PIDs running in namespace; raise RunCommandError on failure."""
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.debug(f"Getting processes in namespace: {namespace}")

    try:
        result = ns_exec(
            ["ip", "netns", "pids", namespace], namespace=None, no_output=True
        )

        pids = []
        for line in result.stdout.strip().splitlines():
            pid_str = line.strip()
            if pid_str and pid_str.isdigit():
                try:
                    pids.append(int(pid_str))
                except ValueError:
                    log.warning(f"Invalid PID format: {pid_str}")

        log.debug(f"Found {len(pids)} processes in namespace {namespace}")
        return pids
    except RunCommandError as e:
        log.error(f"Failed to get processes in namespace {namespace}: {e}")
        raise


def kill_process_in_namespace(pid: int, namespace: str, signal: str = "TERM") -> bool:
    """Send signal to pid inside namespace; return True or raise RunCommandError."""
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError(f"Invalid PID: {pid}")
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.info(f"Killing process {pid} in namespace {namespace} with signal {signal}")

    try:
        ns_exec(["kill", f"-{signal}", str(pid)], namespace=namespace)
        log.info(f"Successfully sent signal {signal} to process {pid}")
        return True
    except RunCommandError as e:
        log.error(f"Failed to kill process {pid} in namespace {namespace}: {e}")
        raise


def get_process_info(pid: int, namespace: str | None = None) -> dict[str, Any]:
    """Return pid and cmd from ps in namespace (None for root); exists=False when not found."""
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError(f"Invalid PID: {pid}")

    log.debug(f"Getting info for process {pid} in namespace {namespace or 'root'}")

    try:
        result = ns_exec(
            ["ps", "-p", str(pid), "-o", "pid,cmd", "--no-headers"],
            namespace=namespace,
            no_output=True,
        )

        if result.stdout.strip():
            parts = result.stdout.strip().split(None, 1)
            return {
                "pid": int(parts[0]) if parts else pid,
                "cmd": parts[1] if len(parts) > 1 else "",
            }
        else:
            return {"pid": pid, "cmd": "", "exists": False}
    except RunCommandError as e:
        log.warning(f"Failed to get process info for PID {pid}: {e}")
        return {"pid": pid, "cmd": "", "exists": False}
