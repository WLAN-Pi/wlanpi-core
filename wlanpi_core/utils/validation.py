"""Validation helpers for values crossing privileged OS boundaries."""

from __future__ import annotations

import re

_INTERFACE_NAME_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.-]{0,14}$")
_NAMESPACE_NAME_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.-]{0,62}$")
_CONFIG_ID_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.-]{0,63}$")
_PHY_NAME_RE = re.compile(r"^phy[0-9]{1,10}$")


def _validate_name(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError(f"invalid {label}")
    if value in {".", ".."} or not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def validate_interface_name(value: str) -> str:
    """Validate a Linux interface name accepted at privileged command boundaries."""
    return _validate_name(value, _INTERFACE_NAME_RE, "interface name")


def validate_namespace_name(value: str) -> str:
    """Validate a named network namespace without allowing path/option syntax."""
    return _validate_name(value, _NAMESPACE_NAME_RE, "namespace name")


def validate_config_id(value: str) -> str:
    """Validate an identifier used as a configuration filename stem."""
    return _validate_name(value, _CONFIG_ID_RE, "configuration ID")


def validate_phy_name(value: str) -> str:
    """Validate the kernel's canonical phyN identifier form."""
    return _validate_name(value, _PHY_NAME_RE, "PHY name")


def validate_vlan_id(value: int | str) -> int:
    """Validate an IEEE 802.1Q VLAN identifier used for network mutation."""
    if isinstance(value, bool):
        raise ValueError("VLAN ID must be an integer from 1 through 4094")
    try:
        vlan_id = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("VLAN ID must be an integer from 1 through 4094") from error
    if str(value).strip() != str(vlan_id) or not 1 <= vlan_id <= 4094:
        raise ValueError("VLAN ID must be an integer from 1 through 4094")
    return vlan_id


def validate_wifi_frequency(value: int) -> int:
    """Validate a 2.4, 5, or 6 GHz WiFi center frequency in MHz."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("WiFi frequency must be an integer")
    in_24_ghz_band = 2400 <= value <= 2500
    in_5_or_6_ghz_band = 4900 <= value <= 7125
    if not (in_24_ghz_band or in_5_or_6_ghz_band):
        raise ValueError("WiFi frequency is outside the supported range")
    return value


def validate_ssid(value: str) -> str:
    """Validate an API string representation of an IEEE 802.11 SSID."""
    if not isinstance(value, str) or not value:
        raise ValueError("SSID must not be empty")
    if len(value.encode("utf-8")) > 32:
        raise ValueError("SSID must not exceed 32 UTF-8 bytes")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("SSID must not contain control characters")
    return value


def validate_wpa_text(value: str, label: str, max_bytes: int = 1024) -> str:
    """Reject control characters before a value is written to WPA config syntax."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{label} is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} must not contain control characters")
    return value
