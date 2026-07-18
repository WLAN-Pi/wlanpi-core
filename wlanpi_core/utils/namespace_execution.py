"""
Namespace execution utilities for running commands in network namespaces.

This module provides reusable functions for executing commands in network namespaces
or in the root namespace. These utilities are used throughout the codebase for
namespace-aware command execution.
"""
import logging
from typing import List, Optional

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.validation import validate_namespace_name

log = logging.getLogger(__name__)


def ns_exec(
    cmd: List[str],
    namespace: Optional[str] = None,
    no_output: bool = False,
    raise_on_fail: bool = True,
) -> CommandResult:
    """
    Execute a command in a network namespace or in the root namespace.

    Args:
        cmd: Command to execute as a list of strings
        namespace: Network namespace name. If None, executes in root namespace.
        no_output: If True, suppresses logging of command output
        raise_on_fail: If True, raises RunCommandError on command failure

    Returns:
        CommandResult object with stdout, stderr, and return_code

    Raises:
        RunCommandError: If raise_on_fail=True and command fails

    Examples:
        >>> # Execute in a namespace
        >>> result = ns_exec(["ip", "addr", "show"], namespace="test_ns")
        
        >>> # Execute in root namespace
        >>> result = ns_exec(["ip", "addr", "show"], namespace=None)
        
        >>> # Execute with error handling
        >>> try:
        ...     result = ns_exec(["invalid", "cmd"], namespace="test_ns")
        ... except RunCommandError as e:
        ...     print(f"Command failed: {e}")
    """
    if namespace is None:
        # Root namespace: use sudo
        full_cmd = ["sudo"] + cmd
    else:
        namespace = validate_namespace_name(namespace)
        # Named namespace: use ip netns exec
        full_cmd = ["sudo", "ip", "netns", "exec", namespace] + cmd

    log.debug(f"Executing in namespace '{namespace or 'root'}': {' '.join(full_cmd)}")

    try:
        result = run_command(full_cmd, raise_on_fail=raise_on_fail)
        
        if not no_output:
            log.debug(f"stdout: {result.stdout}")
            log.debug(f"stderr: {result.stderr}")
            log.debug(f"return_code: {result.return_code}")
        
        return result
    except RunCommandError as e:
        log.error(
            f"Command failed in namespace '{namespace or 'root'}': "
            f"{' '.join(cmd)} - {e}"
        )
        raise
    except Exception as e:
        log.error(
            f"Unexpected error executing command in namespace '{namespace or 'root'}': "
            f"{' '.join(cmd)} - {e}"
        )
        raise


def run_in_namespace(
    namespace: str,
    cmd: List[str],
    no_output: bool = False,
    raise_on_fail: bool = True,
) -> CommandResult:
    """
    Convenience wrapper for executing a command in a specific namespace.

    Args:
        namespace: Network namespace name (must not be None)
        cmd: Command to execute as a list of strings
        no_output: If True, suppresses logging of command output
        raise_on_fail: If True, raises RunCommandError on command failure

    Returns:
        CommandResult object with stdout, stderr, and return_code

    Raises:
        ValueError: If namespace is None
        RunCommandError: If raise_on_fail=True and command fails
    """
    if namespace is None:
        raise ValueError("namespace cannot be None for run_in_namespace. Use run_in_root() instead.")
    
    return ns_exec(cmd, namespace=namespace, no_output=no_output, raise_on_fail=raise_on_fail)


def run_in_root(
    cmd: List[str],
    no_output: bool = False,
    raise_on_fail: bool = True,
) -> CommandResult:
    """
    Convenience wrapper for executing a command in the root namespace.

    Args:
        cmd: Command to execute as a list of strings
        no_output: If True, suppresses logging of command output
        raise_on_fail: If True, raises RunCommandError on command failure

    Returns:
        CommandResult object with stdout, stderr, and return_code

    Raises:
        RunCommandError: If raise_on_fail=True and command fails
    """
    return ns_exec(cmd, namespace=None, no_output=no_output, raise_on_fail=raise_on_fail)
