"""Hotspot-mode helpers (clients, credentials)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from wlanpi_core.constants import HOSTAPD_CONF_FILE, IW_FILE
from wlanpi_core.core.mode_guard import require_mode
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.utils.general import run_command
from wlanpi_core.core.logging import get_logger
from wlanpi_core.utils import network_config

log = get_logger(__name__)

_DEFAULT_AP_IFACE = "wlan0"
_AP_TYPES = {"ap", "__ap"}


def _resolve_hostapd_conf() -> Path:
    path = Path(HOSTAPD_CONF_FILE)
    if path.is_symlink():
        path = path.resolve()
    if path.exists():
        return path
    raise ValidationError("hostapd configuration not found", status_code=503)


def _parse_hostapd_credentials(conf_path: Path) -> dict[str, str]:
    ssid = None
    passphrase = None
    for line in conf_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if key == "ssid":
            ssid = value
        elif key == "wpa_passphrase":
            passphrase = value
    if not ssid or not passphrase:
        raise ValidationError(
            "Could not read SSID and passphrase from hostapd configuration",
            status_code=503,
        )
    return {"ssid": ssid, "passphrase": passphrase}


def _iface_type(
    iface: str,
    namespace: Optional[str] = None,
    status: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    if status is None:
        status = network_config.status()
    ns_key = namespace or "root"
    iface_info = status.get(ns_key, {}).get(iface)
    if not iface_info:
        return None
    raw = iface_info.get("type") or iface_info.get("Type")
    return str(raw).lower() if raw else None


def resolve_ap_interface(iface: Optional[str] = None) -> str:
    """Return an AP-mode interface name, preferring ``iface`` when valid."""
    status = network_config.status()
    if iface:
        iface = iface.strip()
        if not iface:
            raise ValidationError("interface name is required", status_code=400)
        iface_type = _iface_type(iface, status=status)
        if iface_type not in _AP_TYPES:
            raise ValidationError(
                f"Interface {iface} is not in AP mode",
                status_code=422,
            )
        return iface

    for name, info in status.get("root", {}).items():
        raw_type = (info.get("type") or info.get("Type") or "").lower()
        if raw_type in _AP_TYPES:
            return name

    if _iface_type(_DEFAULT_AP_IFACE, status=status) in _AP_TYPES:
        return _DEFAULT_AP_IFACE

    raise ValidationError("No AP-mode wireless interface found", status_code=503)


def get_hotspot_clients(iface: Optional[str] = None) -> dict[str, Any]:
    require_mode("hotspot")
    ap_iface = resolve_ap_interface(iface)
    try:
        output = run_command(
            [IW_FILE, "dev", ap_iface, "station", "dump"],
            raise_on_fail=True,
        ).stdout
    except (RunCommandError, FileNotFoundError) as exc:
        raise ValidationError(
            f"Unable to read station list: {exc}", status_code=503
        ) from exc

    count = len(re.findall(r"^Station\s+", output, flags=re.MULTILINE))
    return {
        "mode": "hotspot",
        "interface": ap_iface,
        "count": count,
    }


def get_hotspot_ssid_passphrase() -> dict[str, str]:
    require_mode("hotspot")
    creds = _parse_hostapd_credentials(_resolve_hostapd_conf())
    return {
        "mode": "hotspot",
        "ssid": creds["ssid"],
        "passphrase": creds["passphrase"],
    }
