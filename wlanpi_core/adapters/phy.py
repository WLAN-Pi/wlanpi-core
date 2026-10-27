"""Wireless PHY queries and namespace moves."""

import logging
from typing import Any

from wlanpi_core.adapters import discovery
from wlanpi_core.constants import IW_FILE, MONITOR_IFACE_PREFIX
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def phy_args(phy: str) -> list[str]:
    """Return the iw arguments that select `phy`, a name (`phy0`) or index (`phy#0`)."""
    return [phy] if phy.startswith("phy#") else ["phy", phy]


def _phy_netdevs(phy: str, namespace: str | None) -> list[discovery.LiveInterface]:
    # ponytail: assumes phyN is index N, false after `iw phy set name`; read
    # `wiphy index` from `iw phy <name> info` if renamed phys appear.
    index = phy.removeprefix("phy#").removeprefix("phy")
    result = ns_exec([IW_FILE, "dev"], namespace=namespace, no_output=True)
    return [
        live
        for live in discovery._parse_iw_dev(result.stdout, namespace)
        if str(live.phy_index) == index
    ]


def _netdev_states(
    phy: str, namespace: str | None
) -> list[tuple[discovery.LiveInterface, bool]]:
    """Return every netdev on `phy` in `namespace` with whether it is up."""
    netdevs = _phy_netdevs(phy, namespace)
    if not netdevs:
        return []
    links = ns_exec(
        ["ip", "-o", "link", "show", "up"], namespace=namespace, no_output=True
    )
    up = {
        line.split(":")[1].strip().split("@")[0]
        for line in links.stdout.splitlines()
        if line.count(":") >= 2
    }
    return [(live, live.name in up) for live in netdevs]


def up_sibling_monitors(iface: str, namespace: str | None) -> list[str]:
    """Return the monitors other than `iface` that are up on its phy.

    Best effort: [] when the state cannot be read.
    """
    try:
        result = ns_exec([IW_FILE, "dev"], namespace=namespace, no_output=True)
        for live in discovery._parse_iw_dev(result.stdout, namespace):
            if live.name == iface:
                return [
                    m.name
                    for m, is_up in _netdev_states(live.phy, namespace)
                    if is_up and m.type == "monitor" and m.name != iface
                ]
    except (RunCommandError, ValueError) as e:
        log.warning(f"Could not list the netdevs next to {iface}: {e}")
    return []


def _is_core_monitor(live: discovery.LiveInterface) -> bool:
    """Whether `live` is one of Core's own `wlanpiN` capture monitors."""
    suffix = live.name.removeprefix(MONITOR_IFACE_PREFIX)
    return live.type == "monitor" and suffix.isdigit() and suffix != live.name


def _move_phy(phy: str, source: str | None, target: str | None) -> None:
    """Move `phy` from `source` to `target`, keeping Core's monitors as they were.

    Every netdev on a phy travels with it, arrives down, and is renamed by
    the kernel to the lowest free `wlanN` when its name is taken in the
    target: a `wlanpi0` monitor can arrive as `wlan1`. Each of Core's
    monitors is found again by its wdev id (kept across the move, unlike
    the name) and brought back up if it was up. One the kernel renamed is
    removed, since under a `wlanN` name it would pass for a managed netdev
    and block Core's own; Core's monitor sync recreates it later. Netdevs
    Core did not create travel untouched (#202).
    """
    try:
        monitors = [
            (live, is_up)
            for live, is_up in _netdev_states(phy, source)
            if _is_core_monitor(live)
        ]
    except (RunCommandError, ValueError) as e:
        log.warning(f"Could not list the netdevs on {phy} before moving it: {e}")
        monitors = []
    where = ["name", target] if target is not None else ["1"]
    ns_exec([IW_FILE, *phy_args(phy), "set", "netns", *where], namespace=source)
    if not monitors:
        return
    try:
        arrived = _phy_netdevs(phy, target)
    except (RunCommandError, ValueError) as e:
        log.warning(f"Could not list {phy}'s netdevs after moving it: {e}")
        return
    for live, was_up in monitors:
        now = next((a for a in arrived if live.wdev and a.wdev == live.wdev), None)
        if now is None:
            # iw without wdev lines: trust the name only on this phy's monitors.
            now = next(
                (a for a in arrived if a.name == live.name and a.type == "monitor"),
                None,
            )
        if now is None:
            log.warning(f"{live.name} did not arrive with {phy}")
            continue
        if now.name != live.name:
            log.error(
                f"{live.name} arrived in {target or 'root'} as {now.name}: that name "
                f"is taken there. Removing it; Core's monitor sync recreates it."
            )
            try:
                ns_exec([IW_FILE, "dev", now.name, "del"], namespace=target)
            except RunCommandError as e:
                log.warning(f"Could not remove {now.name}: {e}")
            continue
        if not was_up:
            continue
        try:
            ns_exec(["ip", "link", "set", now.name, "up"], namespace=target)
        except RunCommandError as e:
            log.warning(f"Could not bring {now.name} back up after moving {phy}: {e}")


def list_phys(namespace: str | None = None) -> list[str]:
    """
    List all PHY devices in a namespace or root.

    Args:
        namespace: Network namespace name, or None for root

    Returns:
        List of PHY names (e.g., ["phy0", "phy1"])

    Raises:
        RunCommandError: If command execution fails
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
    """
    if not phy or not phy.strip():
        raise ValueError("phy cannot be empty")

    log.debug(f"Getting information for PHY: {phy}")

    try:
        phys = list_phys(namespace=namespace)
        if phy not in phys:
            log.debug(f"PHY {phy} not found in namespace {namespace or 'root'}")
            return None

        if namespace is None:
            result = run_command([IW_FILE, "phy", phy, "info"], raise_on_fail=True)
        else:
            result = ns_exec(
                [IW_FILE, "phy", phy, "info"], namespace=namespace, no_output=True
            )

        info = {"name": phy, "exists": True}

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
    """Move a PHY from root into `namespace`; its netdevs travel with it (see _move_phy).

    Args:
        phy: PHY name (e.g., "phy0") or index selector (e.g., "phy#0")
        namespace: Target namespace name

    Returns:
        True if successful

    Raises:
        RunCommandError: If move operation fails
        ValueError: If phy or namespace is invalid
    """
    if not phy or not phy.strip():
        raise ValueError("phy cannot be empty")
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.info(f"Moving PHY {phy} to namespace {namespace}")
    try:
        _move_phy(phy, None, namespace)
        log.info(f"Successfully moved PHY {phy} to namespace {namespace}")
        return True
    except RunCommandError as e:
        log.error(f"Failed to move PHY {phy} to namespace {namespace}: {e}")
        raise


def move_phy_to_root(phy: str, namespace: str) -> bool:
    """Move a PHY from `namespace` back to root; its netdevs travel with it (see _move_phy).

    Args:
        phy: PHY name (e.g., "phy0") or index selector (e.g., "phy#0")
        namespace: Source namespace name

    Returns:
        True if successful

    Raises:
        RunCommandError: If move operation fails
        ValueError: If phy or namespace is invalid
    """
    if not phy or not phy.strip():
        raise ValueError("phy cannot be empty")
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.info(f"Moving PHY {phy} from namespace {namespace} to root")
    try:
        _move_phy(phy, namespace, None)
        log.info(f"Successfully moved PHY {phy} to root namespace")
        return True
    except RunCommandError as e:
        log.error(f"Failed to move PHY {phy} from namespace {namespace} to root: {e}")
        raise
