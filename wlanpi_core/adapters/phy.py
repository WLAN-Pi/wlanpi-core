"""
PHY (physical device) operations for wireless adapters.

This module provides functions for managing wireless PHY devices, including
moving them between namespaces and querying their state.
"""

import logging
from typing import Any

from wlanpi_core.adapters import discovery
from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def phy_args(phy: str) -> list[str]:
    """Return the iw arguments that select `phy`, a name (`phy0`) or index (`phy#0`)."""
    return [phy] if phy.startswith("phy#") else ["phy", phy]


def _phy_netdevs(phy: str, namespace: str | None) -> list[discovery.LiveInterface]:
    # ponytail: assumes phyN is phy index N, as the callers already do.
    index = phy.removeprefix("phy#").removeprefix("phy")
    result = ns_exec([IW_FILE, "dev"], namespace=namespace, no_output=True)
    return [
        live
        for live in discovery._parse_iw_dev(result.stdout, namespace)
        if str(live.phy_index) == index
    ]


def _up_monitors(phy: str, namespace: str | None) -> list[str]:
    """Return the monitor netdevs on `phy` that are up in `namespace`.

    A netns move takes every netdev of the phy down. Monitors (`wlanpiN`, the
    capture targets) are brought back up; Core ups a managed netdev itself
    when it configures one, and one handed back stays down. Best effort: []
    when the state cannot be read.
    """
    try:
        monitors = [m for m in _phy_netdevs(phy, namespace) if m.type == "monitor"]
        links = ns_exec(
            ["ip", "-o", "link", "show", "up"], namespace=namespace, no_output=True
        )
    except (RunCommandError, ValueError) as e:
        log.warning(f"Could not read which monitors of {phy} are up: {e}")
        return []
    up = {
        line.split(":")[1].strip().split("@")[0]
        for line in links.stdout.splitlines()
        if line.count(":") >= 2
    }
    return [m.name for m in monitors if m.name in up]


def _bring_up(phy: str, names: list[str], namespace: str | None) -> None:
    """Bring `names` up again in `namespace` if they are still `phy`'s monitors.

    The kernel renames a travelling netdev whose name is taken in the target,
    so a name is only trusted if it is still a monitor on this phy there.
    """
    if not names:
        return
    try:
        here = {m.name for m in _phy_netdevs(phy, namespace) if m.type == "monitor"}
    except (RunCommandError, ValueError) as e:
        log.warning(f"Could not list {phy}'s netdevs after moving it: {e}")
        return
    for name in names:
        if name not in here:
            log.warning(f"{name} did not arrive with {phy}; not bringing it up")
            continue
        try:
            ns_exec(["ip", "link", "set", name, "up"], namespace=namespace)
        except RunCommandError as e:
            log.warning(f"Could not bring {name} back up after moving {phy}: {e}")


def list_phys(namespace: str | None = None) -> list[str]:
    """
    List all PHY devices in a namespace or root.

    Args:
        namespace: Network namespace name, or None for root

    Returns:
        List of PHY names (e.g., ["phy0", "phy1"])

    Raises:
        RunCommandError: If command execution fails

    Examples:
        >>> phys = list_phys()
        >>> print(f"Found {len(phys)} PHY devices")
    """
    log.debug(f"Listing PHY devices in namespace {namespace or 'root'}")

    try:
        if namespace is None:
            result = run_command([IW_FILE, "phy"], raise_on_fail=True)
        else:
            result = ns_exec([IW_FILE, "phy"], namespace=namespace, no_output=True)

        phys = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Wiphy"):
                # Format: "Wiphy phy0" or "Wiphy phy1"
                parts = line.split()
                if len(parts) >= 2:
                    phy_name = parts[1]
                    if phy_name.startswith("phy"):
                        phys.append(phy_name)

        log.debug(f"Found {len(phys)} PHY devices")
        return phys
    except RunCommandError as e:
        log.error(f"Failed to list PHY devices: {e}")
        raise


def get_phy_info(phy: str, namespace: str | None = None) -> dict[str, Any] | None:
    """
    Get information about a specific PHY device.

    Args:
        phy: PHY name (e.g., "phy0")
        namespace: Network namespace name, or None for root

    Returns:
        Dictionary with PHY information, or None if not found

    Raises:
        RunCommandError: If command execution fails
        ValueError: If phy name is invalid

    Examples:
        >>> info = get_phy_info("phy0")
        >>> if info:
        ...     print(f"PHY name: {info.get('name')}")
    """
    if not phy or not phy.strip():
        raise ValueError("phy cannot be empty")

    log.debug(f"Getting information for PHY: {phy}")

    try:
        # Check if PHY exists
        phys = list_phys(namespace=namespace)
        if phy not in phys:
            log.debug(f"PHY {phy} not found in namespace {namespace or 'root'}")
            return None

        # Get detailed info using 'iw phy <phy> info'
        if namespace is None:
            result = run_command([IW_FILE, "phy", phy, "info"], raise_on_fail=True)
        else:
            result = ns_exec(
                [IW_FILE, "phy", phy, "info"], namespace=namespace, no_output=True
            )

        info = {"name": phy, "exists": True}

        # Parse basic info from output (can be extended with more fields)
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Wiphy"):
                parts = line.split()
                if len(parts) >= 2:
                    info["wiphy"] = parts[1]

        log.debug(f"Retrieved info for PHY {phy}")
        return info
    except RunCommandError as e:
        log.error(f"Failed to get PHY info for {phy}: {e}")
        raise


def move_phy_to_namespace(phy: str, namespace: str) -> bool:
    """
    Move a PHY device to a network namespace.

    Args:
        phy: PHY name (e.g., "phy0") or index selector (e.g., "phy#0")
        namespace: Target namespace name

    Returns:
        True if successful

    Raises:
        RunCommandError: If move operation fails
        ValueError: If phy or namespace is invalid

    Examples:
        >>> move_phy_to_namespace("phy0", "test_ns")
    """
    if not phy or not phy.strip():
        raise ValueError("phy cannot be empty")
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.info(f"Moving PHY {phy} to namespace {namespace}")

    up = _up_monitors(phy, None)
    try:
        # Move PHY to namespace using 'iw phy <phy> set netns name <namespace>'
        run_command(
            ["sudo", IW_FILE, *phy_args(phy), "set", "netns", "name", namespace],
            raise_on_fail=True,
        )
        _bring_up(phy, up, namespace)

        log.info(f"Successfully moved PHY {phy} to namespace {namespace}")
        return True
    except RunCommandError as e:
        log.error(f"Failed to move PHY {phy} to namespace {namespace}: {e}")
        raise


def move_phy_to_root(phy: str, namespace: str) -> bool:
    """
    Move a PHY device from a namespace back to root namespace.

    Args:
        phy: PHY name (e.g., "phy0") or index selector (e.g., "phy#0")
        namespace: Source namespace name

    Returns:
        True if successful

    Raises:
        RunCommandError: If move operation fails
        ValueError: If phy or namespace is invalid

    Examples:
        >>> move_phy_to_root("phy0", "test_ns")
    """
    if not phy or not phy.strip():
        raise ValueError("phy cannot be empty")
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.info(f"Moving PHY {phy} from namespace {namespace} to root")

    up = _up_monitors(phy, namespace)
    try:
        # Move PHY to root (PID 1) using 'iw phy <phy> set netns 1'
        ns_exec(
            [IW_FILE, *phy_args(phy), "set", "netns", "1"],
            namespace=namespace,
        )
        _bring_up(phy, up, None)

        log.info(f"Successfully moved PHY {phy} to root namespace")
        return True
    except RunCommandError as e:
        log.error(f"Failed to move PHY {phy} from namespace {namespace} to root: {e}")
        raise
