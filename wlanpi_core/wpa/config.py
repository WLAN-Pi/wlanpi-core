"""wpa_supplicant configuration file generation."""

import logging
import os
import string
from pathlib import Path
from typing import Any

from wlanpi_core.schemas.network.network import (
    NamespaceConfig,
    RootConfig,
    SecurityTypes,
)

log = logging.getLogger(__name__)


# wpa_supplicant 2.x reads a "quoted" value literally up to the line's last quote; escapes change it.


def _ssid_value(ssid: str) -> str:
    """Encode an SSID as bare hex, exact for any bytes (quotes, backslashes, UTF-8)."""
    return ssid.encode("utf-8").hex()


def _psk_value(psk: str) -> str:
    """Encode a PSK: 64 hex digits are a raw key; a passphrase is quoted as-is.

    The passphrase is not escaped: wpa_supplicant reads up to the last quote,
    so embedded quotes and backslashes survive. psk does not accept P"...".
    """
    if len(psk) == 64 and all(c in string.hexdigits for c in psk):
        return psk.lower()
    return f'"{psk}"'


def _string_value(value: str) -> str:
    """Encode an EAP string field (identity, password, paths) as P"..." (printf-escaped)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'P"{escaped}"'


def generate_global_header(
    ctrl_interface: str = "/run/wpa_supplicant",
    update_config: int = 1,
) -> str:
    """Return the global section of a wpa_supplicant configuration."""
    lines = [
        f"ctrl_interface={ctrl_interface}",
        f"update_config={update_config}",
        "sae_pwe=2",  # H2E when the AP offers it, as 6 GHz requires
    ]
    return "\n".join(lines)


def generate_network_block(
    cfg: NamespaceConfig | RootConfig,
    priority: int = 0,
) -> str:
    """Return the wpa_supplicant network block for cfg.

    Raises:
        ValueError: If cfg has no security.ssid.
    """
    lines = ["network={"]

    if not cfg.security or not hasattr(cfg.security, "ssid") or not cfg.security.ssid:
        raise ValueError("security.ssid is required when generating network block")

    original_ssid = cfg.security.ssid
    lines.append(f"    ssid={_ssid_value(original_ssid)}")
    lines.append(f"    priority={priority}")

    if hasattr(cfg.security, "security") and cfg.security.security:
        sec_str = (
            cfg.security.security.value
            if isinstance(cfg.security.security, SecurityTypes)
            else str(cfg.security.security)
        )
        sec = sec_str.upper()
    else:
        sec = "OPEN"

    if sec == "OPEN":
        lines.append("    key_mgmt=NONE")
    elif sec == "OWE":
        lines.append("    key_mgmt=OWE")
        lines.append("    ieee80211w=2")
    elif sec in ("WPA2-PSK", "WPA-PSK"):
        if cfg.security.psk:
            lines.append(f"    psk={_psk_value(cfg.security.psk)}")
        lines.append("    key_mgmt=WPA-PSK")
        lines.append("    ieee80211w=1")
    elif sec == "WPA3-PSK":
        if cfg.security.psk:
            lines.append(f"    psk={_psk_value(cfg.security.psk)}")
        # SAE-EXT-KEY (AKM 24) with GCMP-256 for Wi-Fi 7 MLO APs; plain SAE keeps CCMP.
        lines.append("    key_mgmt=SAE SAE-EXT-KEY")
        lines.append("    pairwise=GCMP-256 CCMP")
        lines.append("    group=GCMP-256 CCMP")
        lines.append("    ieee80211w=2")  # PMF required for WPA3
    elif sec in ("802.1X", "WPA2-EAP", "WPA3-EAP"):
        lines.append("    key_mgmt=WPA-EAP")
        if cfg.security.identity:
            lines.append(f"    identity={_string_value(cfg.security.identity)}")
        if cfg.security.password:
            lines.append(f"    password={_string_value(cfg.security.password)}")

        eap_method = getattr(cfg.security, "eap_method", "PEAP")
        lines.append(f"    eap={eap_method}")

        if eap_method == "PEAP":
            phase2_method = getattr(cfg.security, "phase2_method", "MSCHAPV2")
            lines.append(f'    phase2="auth={phase2_method}"')
        elif eap_method == "TLS":
            if cfg.security.client_cert:
                lines.append(
                    f"    client_cert={_string_value(cfg.security.client_cert)}"
                )
            if cfg.security.private_key:
                lines.append(
                    f"    private_key={_string_value(cfg.security.private_key)}"
                )

        ca_cert = cfg.security.ca_cert or "/etc/ssl/certs/ca-certificates.crt"
        lines.append(f"    ca_cert={_string_value(ca_cert)}")

        if sec == "WPA3-EAP":
            lines.append("    ieee80211w=2")
        else:
            lines.append("    ieee80211w=1")

    lines.append("}")
    return "\n".join(lines)


def write_wpa_config(
    cfg: NamespaceConfig | RootConfig,
    conf_path: Path,
    global_settings: dict[str, Any],
    ctrl_interface: str,
) -> None:
    """Write a 0600 wpa_supplicant config holding only this entry's network.

    No other network, so the supplicant cannot fall back to an earlier profile's.

    Raises:
        ValueError: If cfg has no security.ssid.
    """
    if not cfg.security or not hasattr(cfg.security, "ssid") or not cfg.security.ssid:
        raise ValueError("security.ssid is required when writing config with security")

    global_header = generate_global_header(
        ctrl_interface=ctrl_interface,
        update_config=global_settings.get("update_config", 1),
    )
    content = global_header + "\n\n" + generate_network_block(cfg, 1)

    conf_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(conf_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # the create mode does not apply to an existing file
    with os.fdopen(fd, "w") as f:
        f.write(content)
    log.debug(f"Wrote WPA config to {conf_path}")
