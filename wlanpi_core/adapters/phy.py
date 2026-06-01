"""
PHY (physical device) operations for wireless adapters.

This module provides functions for managing wireless PHY devices, including
moving them between namespaces and querying their state.
"""
import logging
from typing import List, Optional

from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def list_phys(namespace: Optional[str] = None) -> List[str]:
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


def get_phy_info(phy: str, namespace: Optional[str] = None) -> Optional[dict]:
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
            result = ns_exec([IW_FILE, "phy", phy, "info"], namespace=namespace, no_output=True)

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
        phy: PHY name (e.g., "phy0")
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

    try:
        # Move PHY to namespace using 'iw phy <phy> set netns name <namespace>'
        run_command(
            ["sudo", IW_FILE, "phy", phy, "set", "netns", "name", namespace],
            raise_on_fail=True,
        )

        log.info(f"Successfully moved PHY {phy} to namespace {namespace}")
        return True
    except RunCommandError as e:
        log.error(f"Failed to move PHY {phy} to namespace {namespace}: {e}")
        raise


def move_phy_to_root(phy: str, namespace: str) -> bool:
    """
    Move a PHY device from a namespace back to root namespace.

    Args:
        phy: PHY name (e.g., "phy0")
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

    try:
        # Move PHY to root (PID 1) using 'iw phy <phy> set netns 1'
        ns_exec(
            [IW_FILE, "phy", phy, "set", "netns", "1"],
            namespace=namespace,
        )

        log.info(f"Successfully moved PHY {phy} to root namespace")
        return True
    except RunCommandError as e:
        log.error(f"Failed to move PHY {phy} from namespace {namespace} to root: {e}")
        raise
