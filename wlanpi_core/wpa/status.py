"""
WPA supplicant status checking and parsing.

This module provides functions for checking wpa_supplicant status and
parsing status information.
"""
import logging
from typing import Optional

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

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

        # Get scan results
        scan = ns_exec(
            ["wpa_cli", "-i", iface, "scan_results"],
            namespace=namespace,
        ).stdout.strip()

        lines = scan.split("\n")
        if len(lines) > 1 and connected_bssid:
            for line in lines[1:]:
                parts = line.split("\t")
                if len(parts) < 5:
                    continue
                bssid, freq_str, signal_str, flags, ssid = parts
                if bssid.lower() == connected_bssid.lower():
                    log.info(f"Found connected network: {parts}")
                    try:
                        signal = int(signal_str)
                    except ValueError:
                        signal = None
                    key_mgmt = parse_key_mgmt(flags)
                    break

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


def parse_key_mgmt(flags: str) -> str:
    """
    Parse key management type from WPA flags.

    Args:
        flags: WPA flags string from scan results

    Returns:
        Key management type string

    Examples:
        >>> key_mgmt = parse_key_mgmt("[WPA2-PSK-CCMP][ESS]")
        >>> assert key_mgmt == "wpa-psk"
    """
    if "WPA2-PSK" in flags:
        return "wpa-psk"
    elif "WPA-PSK" in flags:
        return "wpa-psk"
    elif "WEP" in flags:
        return "wep"
    elif "[ESS]" in flags and "WPA" not in flags:
        return "open"
    return "unknown"
