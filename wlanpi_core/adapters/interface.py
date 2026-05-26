"""
Interface operations for network adapters.

This module provides functions for creating, deleting, and managing network interfaces,
separate from namespace concerns.
"""
import logging
from typing import Optional

from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def create_interface(
    phy: str,
    interface_name: str,
    interface_type: str = "managed",
    namespace: Optional[str] = None,
) -> bool:
    """
    Create a wireless interface from a PHY device.

    Args:
        phy: PHY name (e.g., "phy0")
        interface_name: Name for the new interface (e.g., "wlan0")
        interface_type: Interface type (default: "managed", can be "monitor", "ap", etc.)
        namespace: Network namespace name, or None for root

    Returns:
        True if successful

    Raises:
        RunCommandError: If creation fails
        ValueError: If phy or interface_name is invalid

    Examples:
        >>> create_interface("phy0", "wlan0", "managed")
        >>> create_interface("phy1", "wlan1", "monitor", namespace="test_ns")
    """
    if not phy or not phy.strip():
        raise ValueError("phy cannot be empty")
    if not interface_name or not interface_name.strip():
        raise ValueError("interface_name cannot be empty")

    log.info(
        f"Creating interface {interface_name} (type: {interface_type}) "
        f"from {phy} in namespace {namespace or 'root'}"
    )

    try:
        cmd = [IW_FILE, "phy", phy, "interface", "add", interface_name, "type", interface_type]

        if namespace is None:
            run_command(cmd, raise_on_fail=True)
        else:
            ns_exec(cmd, namespace=namespace)

        log.info(f"Successfully created interface {interface_name}")
        return True
    except RunCommandError as e:
        # Interface might already exist, which is often not a critical error
        if "already exists" in str(e).lower() or "File exists" in str(e):
            log.info(f"Interface {interface_name} already exists")
            return True
        log.error(f"Failed to create interface {interface_name}: {e}")
        raise


def delete_interface(
    interface_name: str, namespace: Optional[str] = None
) -> bool:
    """
    Delete a network interface.

    Args:
        interface_name: Name of the interface to delete
        namespace: Network namespace name, or None for root

    Returns:
        True if successful

    Raises:
        RunCommandError: If deletion fails (unless interface doesn't exist)
        ValueError: If interface_name is invalid

    Examples:
        >>> delete_interface("wlan0")
        >>> delete_interface("wlan1", namespace="test_ns")
    """
    if not interface_name or not interface_name.strip():
        raise ValueError("interface_name cannot be empty")

    log.info(f"Deleting interface {interface_name} in namespace {namespace or 'root'}")

    try:
        cmd = [IW_FILE, "dev", interface_name, "del"]

        if namespace is None:
            run_command(cmd, raise_on_fail=True)
        else:
            ns_exec(cmd, namespace=namespace)

        log.info(f"Successfully deleted interface {interface_name}")
        return True
    except RunCommandError as e:
        # Interface might not exist, which is often not a critical error
        if "No such device" in str(e) or "does not exist" in str(e).lower():
            log.info(f"Interface {interface_name} does not exist, skipping deletion")
            return True
        log.error(f"Failed to delete interface {interface_name}: {e}")
        raise


def get_interface_info(
    interface_name: str, namespace: Optional[str] = None
) -> Optional[dict]:
    """
    Get information about a network interface.

    Args:
        interface_name: Name of the interface
        namespace: Network namespace name, or None for root

    Returns:
        Dictionary with interface information, or None if not found

    Raises:
        RunCommandError: If command execution fails
        ValueError: If interface_name is invalid

    Examples:
        >>> info = get_interface_info("wlan0")
        >>> if info:
        ...     print(f"PHY: {info.get('phy')}")
    """
    if not interface_name or not interface_name.strip():
        raise ValueError("interface_name cannot be empty")

    log.debug(f"Getting information for interface {interface_name}")

    try:
        cmd = [IW_FILE, "dev", interface_name, "info"]

        if namespace is None:
            result = run_command(cmd, raise_on_fail=True)
        else:
            result = ns_exec(cmd, namespace=namespace, no_output=True)

        info = {"name": interface_name, "exists": True}

        # Parse info from output
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Interface"):
                parts = line.split()
                if len(parts) >= 2:
                    info["name"] = parts[1]
            elif line.startswith("wiphy"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        phy_num = int(parts[1])
                        info["phy"] = f"phy{phy_num}"
                    except ValueError:
                        pass
            elif line.startswith("type"):
                parts = line.split()
                if len(parts) >= 2:
                    info["type"] = parts[1]

        log.debug(f"Retrieved info for interface {interface_name}")
        return info
    except RunCommandError as e:
        if "No such device" in str(e) or "does not exist" in str(e).lower():
            log.debug(f"Interface {interface_name} does not exist")
            return None
        log.error(f"Failed to get interface info for {interface_name}: {e}")
        raise


def bring_interface_up(
    interface_name: str, namespace: Optional[str] = None
) -> bool:
    """
    Bring a network interface up.

    Args:
        interface_name: Name of the interface
        namespace: Network namespace name, or None for root

    Returns:
        True if successful

    Raises:
        RunCommandError: If operation fails
        ValueError: If interface_name is invalid

    Examples:
        >>> bring_interface_up("wlan0")
        >>> bring_interface_up("wlan1", namespace="test_ns")
    """
    if not interface_name or not interface_name.strip():
        raise ValueError("interface_name cannot be empty")

    log.debug(f"Bringing interface {interface_name} up in namespace {namespace or 'root'}")

    try:
        cmd = ["ip", "link", "set", interface_name, "up"]

        if namespace is None:
            run_command(cmd, raise_on_fail=True)
        else:
            ns_exec(cmd, namespace=namespace)

        log.debug(f"Interface {interface_name} brought up successfully")
        return True
    except RunCommandError as e:
        log.error(f"Failed to bring interface {interface_name} up: {e}")
        raise


def bring_interface_down(
    interface_name: str, namespace: Optional[str] = None
) -> bool:
    """
    Bring a network interface down.

    Args:
        interface_name: Name of the interface
        namespace: Network namespace name, or None for root

    Returns:
        True if successful

    Raises:
        RunCommandError: If operation fails
        ValueError: If interface_name is invalid

    Examples:
        >>> bring_interface_down("wlan0")
        >>> bring_interface_down("wlan1", namespace="test_ns")
    """
    if not interface_name or not interface_name.strip():
        raise ValueError("interface_name cannot be empty")

    log.debug(f"Bringing interface {interface_name} down in namespace {namespace or 'root'}")

    try:
        cmd = ["ip", "link", "set", interface_name, "down"]

        if namespace is None:
            run_command(cmd, raise_on_fail=True)
        else:
            ns_exec(cmd, namespace=namespace)

        log.debug(f"Interface {interface_name} brought down successfully")
        return True
    except RunCommandError as e:
        log.error(f"Failed to bring interface {interface_name} down: {e}")
        raise
