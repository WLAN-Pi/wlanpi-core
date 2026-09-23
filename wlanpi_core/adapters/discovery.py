"""
Interface discovery and listing.

This module provides functions for discovering and listing network interfaces
on the system.
"""

import logging
from typing import Any, NamedTuple

from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.namespaces import namespace as ns_namespace
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def list_interfaces() -> list[str]:
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


def get_interface_by_name(interface_name: str) -> dict[str, Any] | None:
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
        result = run_command(
            [IW_FILE, "dev", interface_name, "info"], raise_on_fail=True
        )

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


class LiveInterface(NamedTuple):
    """A wireless netdev as the kernel reports it now."""

    name: str
    phy_index: int
    netns: str | None
    type: str
    # Kernel ifindex: unchanged by a netns move, new when a netdev is
    # recreated, so it tells a netdev apart from a later one of the same name.
    ifindex: int | None = None

    @property
    def phy(self) -> str:
        """Return the iw selector for this netdev's phy (`phy#N`)."""
        return f"phy#{self.phy_index}"


def _parse_iw_dev(output: str, netns: str | None) -> list[LiveInterface]:
    """Parse bare `iw dev` output, which groups interfaces under `phy#N`."""
    entries: list[dict[str, Any]] = []
    phy_index: int | None = None
    # The netdev that following `type` lines describe; None under a phy header
    # or an "Unnamed/non-netdev interface" (P2P-device wdev), whose type is not
    # the previous netdev's.
    current: dict[str, Any] | None = None
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("phy#"):
            current = None
            try:
                phy_index = int(line.removeprefix("phy#"))
            except ValueError:
                phy_index = None
        elif line.startswith("Interface ") and phy_index is not None:
            current = {
                "name": line.split()[1],
                "phy_index": phy_index,
                "type": "",
                "ifindex": None,
            }
            entries.append(current)
        elif line.startswith("Unnamed/non-netdev"):
            current = None
        elif line.startswith("type ") and current is not None:
            current["type"] = line.split()[1]
        elif line.startswith("ifindex ") and current is not None:
            try:
                current["ifindex"] = int(line.split()[1])
            except ValueError:
                pass
    return [
        LiveInterface(e["name"], e["phy_index"], netns, e["type"], e["ifindex"])
        for e in entries
    ]


def list_interfaces_all_namespaces() -> list[LiveInterface]:
    """
    List wireless interfaces in the root namespace and every named netns.

    Read-only. A namespace whose `iw dev` fails, or whose name Core's
    validator refuses (the kernel accepts names such as `lab:1`), is logged
    and skipped, so one namespace does not hide the rest of the inventory.

    Returns:
        LiveInterface entries, root namespace first.

    Raises:
        RunCommandError: If `iw dev` fails in the root namespace
    """
    result = run_command([IW_FILE, "dev"], raise_on_fail=True)
    found = _parse_iw_dev(result.stdout, None)
    for netns in ns_namespace.list_namespaces():
        try:
            ns_result = ns_exec([IW_FILE, "dev"], namespace=netns, no_output=True)
        except (RunCommandError, ValueError) as e:
            log.warning(f"Could not list wireless interfaces in {netns}: {e}")
            continue
        found += _parse_iw_dev(ns_result.stdout, netns)
    return found
