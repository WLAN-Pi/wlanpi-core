"""
Interface management within network namespaces.

This module provides functions for listing, moving, and managing network interfaces
within network namespaces.
"""
import logging
from typing import List, Optional

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def get_interfaces_in_namespace(
    namespace: str, include_loopback: bool = False
) -> List[str]:
    """
    Get list of interface names in a network namespace.

    Args:
        namespace: Network namespace name
        include_loopback: If True, include loopback interfaces

    Returns:
        List of interface names

    Raises:
        RunCommandError: If command execution fails

    Examples:
        >>> interfaces = get_interfaces_in_namespace("test_ns")
        >>> print(f"Found {len(interfaces)} interfaces")
    """
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.debug(f"Getting interfaces in namespace: {namespace}")

    try:
        result = ns_exec(["ip", "-o", "link", "show"], namespace=namespace, no_output=True)
        interfaces = []

        for line in result.stdout.splitlines():
            if not line.strip():
                continue

            # Format: '1: lo: <LOOPBACK,UP,LOWER_UP> ...'
            parts = line.split(":", 2)
            if len(parts) >= 2:
                iface_name = parts[1].strip()
                if include_loopback or not iface_name.startswith("lo"):
                    interfaces.append(iface_name)

        log.debug(f"Found {len(interfaces)} interfaces in namespace {namespace}")
        return interfaces
    except RunCommandError as e:
        log.error(f"Failed to get interfaces in namespace {namespace}: {e}")
        raise


def move_interface_to_namespace(
    interface: str,
    namespace: str,
    interface_type: Optional[str] = None,
) -> bool:
    """
    Move a network interface to a namespace.

    For wireless interfaces, this typically involves moving the PHY.
    For wired interfaces, this moves the link directly.

    Args:
        interface: Interface name (e.g., "wlan0", "eth0")
        namespace: Target namespace name
        interface_type: Optional interface type hint ("wlan", "eth", etc.)

    Returns:
        True if successful

    Raises:
        RunCommandError: If move operation fails
        ValueError: If interface or namespace is invalid

    Examples:
        >>> move_interface_to_namespace("wlan0", "test_ns")
    """
    if not interface or not interface.strip():
        raise ValueError("interface cannot be empty")
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.info(f"Moving interface {interface} to namespace {namespace}")

    # Determine interface type if not provided
    if not interface_type:
        if interface.startswith("wlan"):
            interface_type = "wlan"
        elif interface.startswith("eth"):
            interface_type = "eth"
        else:
            interface_type = "generic"

    try:
        if interface_type == "wlan":
            # For wireless interfaces, we need to get the PHY and move it
            # This is typically handled at the PHY level, not interface level
            # For now, try to move the link directly
            log.debug(f"Moving wireless interface {interface} as link")
            ns_exec(
                ["ip", "link", "set", interface, "netns", namespace],
                namespace=None,  # Execute in root
            )
        else:
            # For other interfaces, move the link directly
            log.debug(f"Moving interface {interface} as link")
            ns_exec(
                ["ip", "link", "set", interface, "netns", namespace],
                namespace=None,  # Execute in root
            )

        log.info(f"Successfully moved interface {interface} to namespace {namespace}")
        return True
    except RunCommandError as e:
        log.error(f"Failed to move interface {interface} to namespace {namespace}: {e}")
        raise


def move_interface_to_root(interface: str, namespace: str) -> bool:
    """
    Move a network interface from a namespace back to root namespace.

    Args:
        interface: Interface name
        namespace: Source namespace name

    Returns:
        True if successful

    Raises:
        RunCommandError: If move operation fails
        ValueError: If interface or namespace is invalid

    Examples:
        >>> move_interface_to_root("wlan0", "test_ns")
    """
    if not interface or not interface.strip():
        raise ValueError("interface cannot be empty")
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.info(f"Moving interface {interface} from namespace {namespace} to root")

    try:
        # Move interface to root namespace (PID 1)
        ns_exec(
            ["ip", "link", "set", interface, "netns", "1"],
            namespace=namespace,
        )

        log.info(f"Successfully moved interface {interface} to root namespace")
        return True
    except RunCommandError as e:
        log.error(
            f"Failed to move interface {interface} from namespace {namespace} to root: {e}"
        )
        raise


def bring_interface_up(interface: str, namespace: Optional[str] = None) -> bool:
    """
    Bring a network interface up in a namespace or root.

    Args:
        interface: Interface name
        namespace: Namespace name, or None for root

    Returns:
        True if successful

    Raises:
        RunCommandError: If operation fails

    Examples:
        >>> bring_interface_up("wlan0", "test_ns")
    """
    if not interface or not interface.strip():
        raise ValueError("interface cannot be empty")

    log.debug(f"Bringing interface {interface} up in namespace {namespace or 'root'}")

    try:
        ns_exec(["ip", "link", "set", interface, "up"], namespace=namespace)
        log.debug(f"Interface {interface} brought up successfully")
        return True
    except RunCommandError as e:
        log.error(f"Failed to bring interface {interface} up: {e}")
        raise


def bring_interface_down(interface: str, namespace: Optional[str] = None) -> bool:
    """
    Bring a network interface down in a namespace or root.

    Args:
        interface: Interface name
        namespace: Namespace name, or None for root

    Returns:
        True if successful

    Raises:
        RunCommandError: If operation fails

    Examples:
        >>> bring_interface_down("wlan0", "test_ns")
    """
    if not interface or not interface.strip():
        raise ValueError("interface cannot be empty")

    log.debug(f"Bringing interface {interface} down in namespace {namespace or 'root'}")

    try:
        ns_exec(["ip", "link", "set", interface, "down"], namespace=namespace)
        log.debug(f"Interface {interface} brought down successfully")
        return True
    except RunCommandError as e:
        log.error(f"Failed to bring interface {interface} down: {e}")
        raise
