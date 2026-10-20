"""wpa_supplicant status reading."""

import logging
from typing import Any

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec
from wlanpi_core.utils.network import ssid_text
from wlanpi_core.utils.validation import validate_interface_name
from wlanpi_core.wpa.scan import fetch_scan_results, find_bss, parse_wpa_scan_results
from wlanpi_core.wpa.supplicant import wpa_cli_command

log = logging.getLogger(__name__)


def get_wpa_status(iface: str, namespace: str | None) -> dict[str, Any]:
    """Return wpa_status, ip_info and connected_scan for an interface, or {"error": ...}."""
    iface = validate_interface_name(iface)
    try:
        wpa_status = {}
        wpa = ns_exec(
            wpa_cli_command(iface, namespace, "status"),
            namespace=namespace,
        ).stdout

        for line in wpa.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                # wpa_cli prints SSID edge spaces unescaped; they are SSID bytes.
                wpa_status[key] = value if key == "ssid" else value.strip()

        connected_ssid = ssid_text(wpa_status["ssid"]) if "ssid" in wpa_status else None
        connected_bssid = wpa_status.get("bssid")

        signal = None
        key_mgmt = "unknown"
        try:
            freq = int(wpa_status.get("freq", 0))
        except (TypeError, ValueError):
            log.warning(
                "Ignoring invalid WPA frequency for %s: %r",
                iface,
                wpa_status.get("freq"),
            )
            freq = 0

        if connected_bssid:
            networks = parse_wpa_scan_results(
                fetch_scan_results(iface, namespace),
                include_hidden=True,
            )
            matched = find_bss(networks, connected_bssid)
            if matched is None and wpa_status.get("ap_mld_addr"):
                # MLO: bssid is the AP MLD address, absent from scans; match the
                # link by SSID+freq, only when unique (another AP may share the channel).
                # ponytail: ambiguous matches report signal 0; match
                # `wpa_cli mlo_status` ap_link_addr for an exact link lookup.
                candidates = [
                    n
                    for n in networks
                    if n.get("ssid") == connected_ssid and n.get("freq") == freq
                ]
                if len(candidates) == 1:
                    matched = candidates[0]
            if matched:
                log.info("Found connected network in scan results: %s", matched)
                signal = matched.get("signal")
                key_mgmt = matched.get("key_mgmt", "unknown")

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
