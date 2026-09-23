"""
Process management within network namespaces.

This module provides functions for listing and managing processes running
within network namespaces.
"""

import logging
from typing import Any

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def get_processes_in_namespace(namespace: str) -> list[int]:
    """
    Get list of process IDs (PIDs) running in a network namespace.

    Args:
        namespace: Network namespace name

    Returns:
        List of process IDs (integers)

    Raises:
        RunCommandError: If command execution fails
        ValueError: If namespace is invalid

    Examples:
        >>> pids = get_processes_in_namespace("test_ns")
        >>> print(f"Found {len(pids)} processes")
    """
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.debug(f"Getting processes in namespace: {namespace}")

    try:
        # Use 'ip netns pids' command
        result = ns_exec(
            ["ip", "netns", "pids", namespace], namespace=None, no_output=True
        )

        # Parse PIDs from output (one per line, may have whitespace)
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
    """
    Kill a specific process in a network namespace.

    Args:
        pid: Process ID to kill
        namespace: Network namespace name
        signal: Signal to send (default: "TERM")

    Returns:
        True if successful

    Raises:
        RunCommandError: If kill operation fails
        ValueError: If pid or namespace is invalid

    Examples:
        >>> kill_process_in_namespace(1234, "test_ns", signal="KILL")
    """
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
    """
    Get information about a process (basic implementation).

    Args:
        pid: Process ID
        namespace: Optional namespace name (if None, checks root)

    Returns:
        Dictionary with process information (basic implementation)

    Note:
        This is a basic implementation. For more detailed process info,
        consider using ps or reading from /proc filesystem.

    Examples:
        >>> info = get_process_info(1234, "test_ns")
    """
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError(f"Invalid PID: {pid}")

    log.debug(f"Getting info for process {pid} in namespace {namespace or 'root'}")

    try:
        # Use ps to get basic process info
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
