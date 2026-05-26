"""
Interface discovery and listing.

This module provides functions for discovering and listing network interfaces
on the system.
"""
import logging
from typing import List, Optional

from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command

log = logging.getLogger(__name__)


def list_interfaces() -> List[str]:
    """
    List all wireless interfaces on the system using 'iw dev'.

    Returns:
        List of interface names (e.g., ["wlan0", "wlan1"])

    Raises:
        RunCommandError: If command execution fails

    Examples:
        >>> interfaces = list_interfaces()
        >>> print(f"Found {len(interfaces)} interfaces")
    """
    log.debug("Listing wireless interfaces")

    try:
        result = run_command([IW_FILE, "dev"], raise_on_fail=True)
        interfaces = []

        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Interface"):
                # Format: "Interface wlan0"
                parts = line.split()
                if len(parts) >= 2:
                    interface_name = parts[1]
                    interfaces.append(interface_name)

        log.debug(f"Found {len(interfaces)} wireless interfaces")
        return interfaces
    except RunCommandError as e:
        log.error(f"Failed to list interfaces: {e}")
        raise


def get_interface_by_name(interface_name: str) -> Optional[dict]:
    """
    Get information about a specific interface by name.

    Args:
        interface_name: Name of the interface to query

    Returns:
        Dictionary with interface information, or None if not found

    Raises:
        RunCommandError: If command execution fails

    Examples:
        >>> info = get_interface_by_name("wlan0")
        >>> if info:
        ...     print(f"Interface type: {info.get('type')}")
    """
    if not interface_name or not interface_name.strip():
        raise ValueError("interface_name cannot be empty")

    log.debug(f"Getting information for interface: {interface_name}")

    try:
        # Check if interface exists in the list
        interfaces = list_interfaces()
        if interface_name not in interfaces:
            log.debug(f"Interface {interface_name} not found")
            return None

        # Get detailed info using 'iw dev <interface> info'
        result = run_command([IW_FILE, "dev", interface_name, "info"], raise_on_fail=True)

        # Parse basic info from output
        info = {"name": interface_name, "exists": True}

        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("wiphy"):
                # Extract PHY number
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        phy_num = int(parts[1])
                        info["phy"] = f"phy{phy_num}"
                    except ValueError:
                        pass
            elif line.startswith("type"):
                # Extract interface type
                parts = line.split()
                if len(parts) >= 2:
                    info["type"] = parts[1]

        log.debug(f"Retrieved info for interface {interface_name}")
        return info
    except RunCommandError as e:
        log.error(f"Failed to get interface info for {interface_name}: {e}")
        raise
