"""WPA supplicant scan primitives (wpa_cli scan / scan_results)."""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)

_SCAN_POLL_INTERVAL_SEC = 0.5
_SCAN_POLL_ATTEMPTS = 8


def parse_key_mgmt(flags: str) -> str:
    """Parse key management type from WPA scan-result flags."""
    if "WPA2-PSK" in flags:
        return "wpa-psk"
    if "WPA-PSK" in flags:
        return "wpa-psk"
    if "WEP" in flags:
        return "wep"
    if "[ESS]" in flags and "WPA" not in flags:
        return "open"
    return "unknown"


def parse_wpa_scan_results(
    text: str, include_hidden: bool = True
) -> list[dict[str, Any]]:
    """Parse ``wpa_cli scan_results`` tab-separated output."""
    networks: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}

    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) == 4:
            parts.append("")
        if len(parts) < 5:
            continue
        bssid, freq_str, signal_str, flags, ssid = parts[:5]
        if not include_hidden and not ssid:
            continue
        try:
            freq = int(freq_str)
            signal = int(signal_str)
        except ValueError:
            continue

        entry = {
            "ssid": ssid,
            "bssid": bssid.lower(),
            "signal": signal,
            "freq": freq,
            "key_mgmt": parse_key_mgmt(flags),
            "minrate": 1_000_000,
        }
        existing = seen.get(entry["bssid"])
        if existing is None or entry["signal"] > existing["signal"]:
            seen[entry["bssid"]] = entry

    networks.extend(seen.values())
    networks.sort(key=lambda n: n["signal"], reverse=True)
    return networks


def fetch_scan_results(iface: str, namespace: Optional[str] = None) -> str:
    """Read cached ``wpa_cli scan_results`` without triggering a new scan."""
    return ns_exec(
        ["wpa_cli", "-i", iface, "scan_results"],
        namespace=namespace,
    ).stdout.strip()


def find_bss(
    networks: list[dict[str, Any]], bssid: str
) -> Optional[dict[str, Any]]:
    """Return the scan entry matching ``bssid``, if present."""
    target = bssid.lower()
    for network in networks:
        if network.get("bssid") == target:
            return network
    return None


def run_interface_scan(
    iface: str,
    namespace: Optional[str] = None,
    include_hidden: bool = True,
) -> list[dict[str, Any]]:
    """Trigger scan on ``iface`` and return parsed networks."""
    log.debug(
        "run_interface_scan iface=%s namespace=%r hidden=%s",
        iface,
        namespace,
        include_hidden,
    )
    try:
        ns_exec(["wpa_cli", "-i", iface, "scan"], namespace=namespace)
    except RunCommandError as exc:
        log.warning("wpa_cli scan failed for %s: %r", iface, exc)
        raise

    last_error: Optional[Exception] = None
    for _ in range(_SCAN_POLL_ATTEMPTS):
        time.sleep(_SCAN_POLL_INTERVAL_SEC)
        try:
            networks = parse_wpa_scan_results(
                fetch_scan_results(iface, namespace),
                include_hidden=include_hidden,
            )
        except RunCommandError as exc:
            last_error = exc
            continue

        if networks:
            return networks

    if last_error:
        raise last_error
    return []
