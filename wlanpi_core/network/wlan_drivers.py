"""WLAN adapter driver discovery (USB and PCI)."""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from wlanpi_core.adapters import discovery
from wlanpi_core.constants import ETHTOOL_FILE, IW_FILE
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.network.namespace.namespace_errors import (
    NetworkNamespaceError,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)

_PCI_DEVICE_RE = re.compile(r"/\d{4}:\d{2}:\d{2}\.\d+(?:/|$)")
_DRIVER_INVENTORY_CACHE_TTL_SEC = 2.0
_driver_inventory_cache: tuple[float, dict[str, Any]] | None = None
_driver_inventory_lock = threading.Lock()


def _run(cmd: list[str], namespace: str | None) -> CommandResult:
    """Run `cmd` in root, or inside `namespace`, without raising on failure."""
    if namespace is None:
        return run_command(cmd, raise_on_fail=False)
    return ns_exec(cmd, namespace=namespace, no_output=True, raise_on_fail=False)


def _driver_for_interface(iface: str, namespace: str | None = None) -> str | None:
    try:
        output = _run([ETHTOOL_FILE, "-i", iface], namespace).stdout
        match = re.search(r"driver:\s+(\S+)", output)
        return match.group(1) if match else None
    except (RunCommandError, FileNotFoundError, ValueError):
        return None


def _bus_from_sysfs_path(device_path: Path) -> str | None:
    """Classify bus from resolved ieee80211 phy device sysfs path."""
    try:
        resolved = str(device_path.resolve())
    except OSError:
        return None
    return _bus_from_resolved_path(resolved)


def _bus_from_resolved_path(resolved: str) -> str | None:
    """Classify bus from a resolved sysfs device path."""
    if "/usb" in resolved:
        return "usb"
    if "/pci" in resolved or _PCI_DEVICE_RE.search(resolved):
        return "pci"
    if "/platform/" in resolved or "/mmc" in resolved or "/sdio" in resolved:
        return "platform"
    return None


def _bus_for_interface(iface: str, namespace: str | None = None) -> str | None:
    try:
        info = _run([IW_FILE, "dev", iface, "info"], namespace).stdout
        match = re.search(r"wiphy\s+(\d+)", info)
        if not match:
            return None
        wiphy = match.group(1)
        device_path = Path(f"/sys/class/ieee80211/phy{wiphy}/device")
        if namespace is not None:
            # A phy moved into a netns leaves the root sysfs; `ip netns exec`
            # mounts that namespace's sysfs, so resolve the path in there.
            resolved = _run(["readlink", "-f", str(device_path)], namespace)
            return _bus_from_resolved_path(resolved.stdout.strip())
        if not device_path.exists():
            return None
        return _bus_from_sysfs_path(device_path)
    except (RunCommandError, FileNotFoundError, OSError, ValueError):
        pass
    return None


def _collect_wlan_driver_inventory() -> dict[str, Any]:
    """Collect one hardware snapshot shared by the USB and PCI views."""
    pci_devices: list[dict[str, str]] = []
    try:
        for line in run_command(["lspci"], raise_on_fail=False).stdout.splitlines():
            if not re.search(r"network controller|wireless", line, re.I):
                continue
            pci_id, _, description = line.partition(" ")
            pci_devices.append(
                {"pci_id": pci_id.strip(), "description": description.strip()}
            )
    except (RunCommandError, FileNotFoundError):
        pci_devices = []

    interfaces: list[tuple[str, str | None]] = []
    try:
        try:
            interfaces = [
                (live.name, live.netns)
                for live in discovery.list_interfaces_all_namespaces()
            ]
        except NetworkNamespaceError as exc:
            log.warning("Could not list namespaces; root only: %r", exc)
            interfaces = [(name, None) for name in discovery.list_interfaces()]
    except RunCommandError as exc:
        log.warning("Could not list WLAN interfaces: %r", exc)

    adapters: list[dict[str, Any]] = []
    for iface, namespace in interfaces:
        bus = _bus_for_interface(iface, namespace)
        if bus not in ("usb", "pci", "platform"):
            continue
        adapters.append(
            {
                "interface": iface,
                "namespace": namespace,
                "driver": _driver_for_interface(iface, namespace),
                "bus": bus,
            }
        )

    return {
        "adapters": adapters,
        "pci_devices": pci_devices,
        "interfaces_scanned": len(interfaces),
    }


def _get_wlan_driver_inventory() -> dict[str, Any]:
    """Return a bounded hardware snapshot, refreshing it after two seconds."""
    global _driver_inventory_cache

    now = time.monotonic()
    with _driver_inventory_lock:
        if _driver_inventory_cache is not None:
            cached_at, inventory = _driver_inventory_cache
            if now - cached_at < _DRIVER_INVENTORY_CACHE_TTL_SEC:
                return inventory

        inventory = _collect_wlan_driver_inventory()
        _driver_inventory_cache = (time.monotonic(), inventory)
        return inventory


def _clear_wlan_driver_inventory_cache() -> None:
    """Clear the single-entry inventory cache (used by tests and invalidation)."""
    global _driver_inventory_cache
    with _driver_inventory_lock:
        _driver_inventory_cache = None


def get_usb_wlan_drivers() -> dict[str, Any]:
    """List wireless interfaces attached via USB with driver names."""
    inventory = _get_wlan_driver_inventory()
    return {
        "adapters": [
            dict(adapter)
            for adapter in inventory["adapters"]
            if adapter["bus"] == "usb"
        ],
        "interfaces_scanned": inventory["interfaces_scanned"],
    }


def get_pci_wlan_drivers() -> dict[str, Any]:
    """List PCI wireless devices and matched WLAN interfaces."""
    inventory = _get_wlan_driver_inventory()
    return {
        "adapters": [
            dict(adapter)
            for adapter in inventory["adapters"]
            if adapter["bus"] in ("pci", "platform")
        ],
        "pci_devices": [dict(device) for device in inventory["pci_devices"]],
        "interfaces_scanned": inventory["interfaces_scanned"],
    }
