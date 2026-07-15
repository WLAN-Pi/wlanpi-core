"""
WPA supplicant configuration file generation.

This module provides functions for generating wpa_supplicant configuration files,
including global headers and network blocks.
"""
import logging
from pathlib import Path
from typing import Union

from wlanpi_core.schemas.network.network import (
    NamespaceConfig,
    RootConfig,
    SecurityTypes,
)

log = logging.getLogger(__name__)


def _quote_wpa_value(value: str) -> str:
    """Quote a validated value for wpa_supplicant configuration syntax."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def generate_global_header(
    ctrl_interface: str = "/run/wpa_supplicant",
    update_config: int = 1,
) -> str:
    """
    Generate the global header for wpa_supplicant configuration.

    Args:
        ctrl_interface: Control interface path
        update_config: Update config flag (0 or 1)

    Returns:
        Global header string

    Examples:
        >>> header = generate_global_header()
        >>> print(header)
    """
    lines = [
        f"ctrl_interface={ctrl_interface}",
        f"update_config={update_config}",
        f"sae_pwe=2",  # SAE PWE in global context
    ]
    return "\n".join(lines)


def generate_network_block(
    cfg: Union[NamespaceConfig, RootConfig],
    priority: int = 0,
) -> str:
    """
    Generate a network block for wpa_supplicant configuration.

    Args:
        cfg: Network configuration (NamespaceConfig or RootConfig)
        priority: Network priority

    Returns:
        Network block string

    Raises:
        ValueError: If security.ssid is required but missing

    Examples:
        >>> block = generate_network_block(config, priority=1)
    """
    lines = ["network={"]

    # Validate security.ssid exists before accessing
    if not cfg.security or not hasattr(cfg.security, 'ssid') or not cfg.security.ssid:
        raise ValueError("security.ssid is required when generating network block")

    # Preserve exact SSID case
    original_ssid = cfg.security.ssid
    lines.append(f"    ssid={_quote_wpa_value(original_ssid)}")
    lines.append(f"    priority={priority}")

    # Get security type safely
    if hasattr(cfg.security, 'security') and cfg.security.security:
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
            lines.append(f"    psk={_quote_wpa_value(cfg.security.psk)}")
        lines.append("    key_mgmt=WPA-PSK")
        lines.append("    ieee80211w=1")
    elif sec == "WPA3-PSK":
        if cfg.security.psk:
            lines.append(f"    psk={_quote_wpa_value(cfg.security.psk)}")
        lines.append("    key_mgmt=SAE")  # WPA3 uses SAE
        lines.append("    ieee80211w=2")  # PMF required for WPA3
    elif sec in ("802.1X", "WPA2-EAP", "WPA3-EAP"):
        lines.append("    key_mgmt=WPA-EAP")
        if cfg.security.identity:
            lines.append(f"    identity={_quote_wpa_value(cfg.security.identity)}")
        if cfg.security.password:
            lines.append(f"    password={_quote_wpa_value(cfg.security.password)}")

        # Enhanced EAP method support
        eap_method = getattr(cfg.security, 'eap_method', 'PEAP')
        lines.append(f"    eap={eap_method}")

        if eap_method == "PEAP":
            phase2_method = getattr(cfg.security, 'phase2_method', 'MSCHAPV2')
            lines.append(f'    phase2="auth={phase2_method}"')
        elif eap_method == "TLS":
            if cfg.security.client_cert:
                lines.append(
                    f"    client_cert={_quote_wpa_value(cfg.security.client_cert)}"
                )
            if cfg.security.private_key:
                lines.append(
                    f"    private_key={_quote_wpa_value(cfg.security.private_key)}"
                )

        ca_cert = cfg.security.ca_cert or "/etc/ssl/certs/ca-certificates.crt"
        lines.append(f"    ca_cert={_quote_wpa_value(ca_cert)}")

        if sec == "WPA3-EAP":
            lines.append("    ieee80211w=2")
        else:
            lines.append("    ieee80211w=1")

    if cfg.mlo:
        lines.append("    mlo=1")

    lines.append("}")
    return "\n".join(lines)


def write_wpa_config(
    cfg: Union[NamespaceConfig, RootConfig],
    config_dir: Path,
    global_settings: dict,
) -> None:
    """
    Write wpa_supplicant configuration file(s) for an interface.

    This function generates both interface.conf and wlan<index>.conf files
    if the interface follows the wlan pattern.

    Args:
        cfg: Network configuration
        config_dir: Directory for configuration files
        global_settings: Global settings dictionary

    Raises:
        ValueError: If security.ssid is required but missing

    Examples:
        >>> write_wpa_config(config, Path("/etc/wpa_supplicant"), {"ctrl_interface": "/run/wpa_supplicant"})
    """
    iface = cfg.iface_display_name or cfg.interface

    # Validate security.ssid exists before accessing
    if not cfg.security or not hasattr(cfg.security, 'ssid') or not cfg.security.ssid:
        raise ValueError("security.ssid is required when writing config with security")

    # Generate both interface.conf and wlan<index>.conf files
    conf_files = [config_dir / f"{iface}.conf"]

    # Add wlan<index>.conf if interface follows wlan pattern
    if iface.startswith("wlan") and len(iface) > 4:
        try:
            index = iface[4:]
            if index.isdigit():
                conf_files.append(config_dir / f"wlan{index}.conf")
        except Exception:
            pass

    for conf_path in conf_files:
        # Find max priority
        max_priority = 0
        blocks = []

        if conf_path.exists():
            with conf_path.open() as f:
                block, in_block = [], False
                for line in f:
                    line = line.strip()
                    if line.startswith("network={"):
                        in_block = True
                        block = [line]
                    elif in_block:
                        block.append(line)
                        if line == "}":
                            blocks.append("\n".join(block))
                            in_block = False

            for b in blocks:
                for l in b.splitlines():
                    if l.strip().startswith("priority="):
                        try:
                            max_priority = max(max_priority, int(l.split("=")[1]))
                        except ValueError:
                            pass

        new_block = generate_network_block(cfg, max_priority + 1)

        # Case-sensitive SSID removal
        original_ssid = cfg.security.ssid
        filtered_blocks = []
        for b in blocks:
            if f'ssid="{original_ssid}"' not in b:
                filtered_blocks.append(b)

        filtered_blocks.insert(0, new_block)

        global_header = generate_global_header(
            ctrl_interface=global_settings.get('ctrl_interface', '/run/wpa_supplicant'),
            update_config=global_settings.get('update_config', 1),
        )

        with conf_path.open("w") as f:
            f.write(global_header + "\n\n" + "\n\n".join(filtered_blocks))

        log.debug(f"Wrote WPA config to {conf_path}")
