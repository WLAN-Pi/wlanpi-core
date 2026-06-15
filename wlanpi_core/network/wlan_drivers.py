"""WLAN adapter driver discovery (USB and PCI)."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from wlanpi_core.adapters import discovery
from wlanpi_core.constants import ETHTOOL_FILE, IW_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command

log = logging.getLogger(__name__)

_PCI_DEVICE_RE = re.compile(r"/\d{4}:\d{2}:\d{2}\.\d+(?:/|$)")


def _driver_for_interface(iface: str) -> str | None:
    try:
        output = run_command([ETHTOOL_FILE, "-i", iface], raise_on_fail=False).stdout
        match = re.search(r"driver:\s+(\S+)", output)
        return match.group(1) if match else None
    except (RunCommandError, FileNotFoundError):
        return None


def _bus_from_sysfs_path(device_path: Path) -> str | None:
    """Classify bus from resolved ieee80211 phy device sysfs path."""
    try:
        resolved = str(device_path.resolve())
    except OSError:
        return None
    if "/usb" in resolved:
        return "usb"
    if "/pci" in resolved or _PCI_DEVICE_RE.search(resolved):
        return "pci"
    if "/platform/" in resolved or "/mmc" in resolved or "/sdio" in resolved:
        return "platform"
    return None


def _bus_for_interface(iface: str) -> str | None:
    try:
        info = run_command([IW_FILE, "dev", iface, "info"], raise_on_fail=False).stdout
        match = re.search(r"wiphy\s+(\d+)", info)
        if not match:
            return None
        wiphy = match.group(1)
        device_path = Path(f"/sys/class/ieee80211/phy{wiphy}/device")
        if not device_path.exists():
            return None
        return _bus_from_sysfs_path(device_path)
    except (RunCommandError, FileNotFoundError, OSError):
        pass
    return None


def get_usb_wlan_drivers() -> dict[str, Any]:
    """List wireless interfaces attached via USB with driver names."""
    adapters: list[dict[str, Any]] = []
    try:
        interfaces = discovery.list_interfaces()
    except RunCommandError as exc:
        log.warning("Could not list WLAN interfaces: %r", exc)
        return {"adapters": adapters, "interfaces_scanned": 0}

    for iface in interfaces:
        if _bus_for_interface(iface) != "usb":
            continue
        adapters.append(
            {
                "interface": iface,
                "driver": _driver_for_interface(iface),
                "bus": "usb",
            }
        )
    return {"adapters": adapters, "interfaces_scanned": len(interfaces)}


def get_pci_wlan_drivers() -> dict[str, Any]:
    """List PCI wireless devices and matched WLAN interfaces."""
    adapters: list[dict[str, Any]] = []
    pci_devices: list[dict[str, str]] = []

    try:
        for line in run_command(["lspci"], raise_on_fail=False).stdout.splitlines():
            if not re.search(r"network controller|wireless", line, re.I):
                continue
            pci_id, _, description = line.partition(" ")
            pci_devices.append({"pci_id": pci_id.strip(), "description": description.strip()})
    except (RunCommandError, FileNotFoundError):
        pci_devices = []

    try:
        interfaces = discovery.list_interfaces()
    except RunCommandError as exc:
        log.warning("Could not list WLAN interfaces: %r", exc)
        interfaces = []

    for iface in interfaces:
        bus = _bus_for_interface(iface)
        if bus not in ("pci", "platform"):
            continue
        adapters.append(
            {
                "interface": iface,
                "driver": _driver_for_interface(iface),
                "bus": bus,
            }
        )

    return {
        "adapters": adapters,
        "pci_devices": pci_devices,
        "interfaces_scanned": len(interfaces),
    }
