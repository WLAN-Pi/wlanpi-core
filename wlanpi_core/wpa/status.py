"""
WPA supplicant status checking and parsing.

This module provides functions for checking wpa_supplicant status and
parsing status information.
"""
import logging
from typing import Optional

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec
from wlanpi_core.wpa.scan import fetch_scan_results, find_bss, parse_wpa_scan_results
from wlanpi_core.utils.validation import validate_interface_name

log = logging.getLogger(__name__)


def get_wpa_status(iface: str, namespace: Optional[str]) -> dict:
    """
    Get wpa_supplicant status for an interface.

    Args:
        iface: Interface name
        namespace: Network namespace name, or None for root

    Returns:
        Dictionary with wpa_status, ip_info, and connected_scan information

    Raises:
        RunCommandError: If status check fails

    Examples:
        >>> status = get_wpa_status("wlan0", "test_ns")
        >>> print(status.get("wpa_status", {}).get("wpa_state"))
    """
    iface = validate_interface_name(iface)
    try:
        wpa_status = {}
        wpa = ns_exec(
            ["wpa_cli", "-i", iface, "status"],
            namespace=namespace,
        ).stdout.strip()

        for line in wpa.split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                wpa_status[key.strip()] = value.strip()

        connected_ssid = wpa_status.get("ssid")
        connected_bssid = wpa_status.get("bssid")

        signal = None
        key_mgmt = "unknown"
        freq = int(wpa_status.get("freq", 0))

        if connected_bssid:
            networks = parse_wpa_scan_results(
                fetch_scan_results(iface, namespace),
                include_hidden=True,
            )
            matched = find_bss(networks, connected_bssid)
            if matched:
                log.info("Found connected network in scan results: %s", matched)
                signal = matched.get("signal")
                key_mgmt = matched.get("key_mgmt", "unknown")

        # Get IP information
        ip = ns_exec(["ip", "addr", "show", iface], namespace=namespace).stdout.strip()

        return {
            "wpa_status": wpa_status,
            "ip_info": ip,
            "connected_scan": {
                "ssid": connected_ssid,
                "bssid": connected_bssid,
                "key_mgmt": key_mgmt,
                "freq": freq,
                "signal": signal if isinstance(signal, int) else 0,
                "minrate": 1000000,
            },
        }

    except RunCommandError as e:
        log.warning(f"Status check failed for {iface}: {e}")
        return {"error": str(e)}
