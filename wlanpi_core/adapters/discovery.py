"""Wireless interface discovery."""

import logging
import re
import subprocess
from typing import Any, NamedTuple

from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.network.namespace.namespace_errors import (
    NetworkNamespaceError,
)
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
    """
    log.debug("Listing wireless interfaces")

    try:
        result = run_command([IW_FILE, "dev"], raise_on_fail=True)
        interfaces = []

        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Interface"):
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
    """
    if not interface_name or not interface_name.strip():
        raise ValueError("interface_name cannot be empty")

    log.debug(f"Getting information for interface: {interface_name}")

    try:
        interfaces = list_interfaces()
        if interface_name not in interfaces:
            log.debug(f"Interface {interface_name} not found")
            return None

        result = run_command(
            [IW_FILE, "dev", interface_name, "info"], raise_on_fail=True
        )

        info = {"name": interface_name, "exists": True}

        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("wiphy"):
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
        log.error(f"Failed to get interface info for {interface_name}: {e}")
        raise


class LiveInterface(NamedTuple):
    """A wireless netdev as the kernel reports it now."""

    name: str
    phy_index: int
    netns: str | None
    type: str
    # Kernel ifindex, per network namespace: a netns move may change it.
    ifindex: int | None = None
    # cfg80211 wdev id: kept across netns moves and new when a netdev is
    # recreated, so it tells a netdev apart from a later one of the same name.
    wdev: str | None = None
    # The radio's permanent MAC: the one identity that survives a rename, a
    # netns move, a replug and a reboot. None when it could not be read.
    phy_mac: str | None = None

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
                "wdev": None,
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
        elif line.startswith("wdev ") and current is not None:
            current["wdev"] = line.split()[1]
    return [
        LiveInterface(
            e["name"], e["phy_index"], netns, e["type"], e["ifindex"], e["wdev"]
        )
        for e in entries
    ]


_MAC_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")


def phy_mac(phy_index: int, namespace: str | None) -> str | None:
    """Return the permanent MAC of `phy#<phy_index>` as seen in `namespace`, or None.

    Read from sysfs inside the namespace, since a moved phy is hidden from
    root's. The netdev `addr` is not an identity: drivers with several
    addresses (iwlwifi, hwsim) give a second vif on the radio a different one.
    """
    # ponytail: assumes phyN is index N, false after `iw phy set name`.
    path = f"/sys/class/ieee80211/phy{phy_index}/macaddress"
    try:
        if namespace is None:
            result = run_command(["cat", path], raise_on_fail=False)
        else:
            result = ns_exec(["cat", path], namespace=namespace, no_output=True)
    except (RunCommandError, ValueError, OSError, subprocess.TimeoutExpired) as e:
        log.warning(f"Could not read the MAC of phy{phy_index}: {e}")
        return None
    mac = result.stdout.strip().lower()
    return mac if _MAC_RE.match(mac) else None


def _with_phy_macs(entries: list[LiveInterface]) -> list[LiveInterface]:
    """Fill `phy_mac` on `entries` (all from one namespace), one read per phy."""
    macs: dict[int, str | None] = {}
    for live in entries:
        if live.phy_index not in macs:
            macs[live.phy_index] = phy_mac(live.phy_index, live.netns)
    return [live._replace(phy_mac=macs[live.phy_index]) for live in entries]


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
    found = _with_phy_macs(_parse_iw_dev(result.stdout, None))
    for netns in ns_namespace.list_namespaces():
        try:
            ns_result = ns_exec([IW_FILE, "dev"], namespace=netns, no_output=True)
        except (RunCommandError, ValueError, OSError, subprocess.TimeoutExpired) as e:
            log.warning(f"Could not list wireless interfaces in {netns}: {e}")
            continue
        found += _with_phy_macs(_parse_iw_dev(ns_result.stdout, netns))
    return found


def list_namespaced_interfaces() -> list[LiveInterface]:
    """Return wireless interfaces in named namespaces; [] if listing fails."""
    try:
        return [
            live for live in list_interfaces_all_namespaces() if live.netns is not None
        ]
    except (
        RunCommandError,
        NetworkNamespaceError,
        OSError,
        subprocess.TimeoutExpired,
    ) as exc:
        log.warning(f"Could not list namespaced wireless interfaces: {exc}")
        return []


def interface_driver(iface: str, namespace: str | None = None) -> str | None:
    """Return the kernel driver bound to `iface` (e.g. `iwlwifi`), or None.

    Reads `/sys/class/net/<iface>/device/driver`, as wlanpi-profiler does,
    inside `namespace`: `ip netns exec` mounts that namespace's sysfs, and a
    phy moved into a namespace is hidden from the root one.
    """
    try:
        result = ns_exec(
            ["readlink", "-f", f"/sys/class/net/{iface}/device/driver"],
            namespace=namespace,
            no_output=True,
            raise_on_fail=False,
        )
    except (RunCommandError, ValueError) as e:
        log.warning(f"Could not read the driver of {iface}: {e}")
        return None
    return result.stdout.strip().rpartition("/")[2] or None
