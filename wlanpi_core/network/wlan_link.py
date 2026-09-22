"""Wireless association information via ``iw link``."""

from __future__ import annotations

import logging
import re
from typing import Any

from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec
from wlanpi_core.utils.validation import validate_interface_name

log = logging.getLogger(__name__)


def _parse_iw_link(stdout: str) -> dict[str, Any]:
    """Parse ``iw dev <iface> link`` output into structured fields."""
    text = stdout.strip()
    if not text or text.startswith("Not connected"):
        return {"connected": False}

    parsed: dict[str, Any] = {"connected": True}

    bssid = re.search(r"Connected to ([0-9a-fA-F:]{17})", text)
    if bssid:
        parsed["bssid"] = bssid.group(1)

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("SSID:"):
            parsed["ssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("freq:"):
            try:
                parsed["freq_mhz"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("signal:"):
            match = re.search(r"(-?\d+(?:\.\d+)?)", line)
            if match:
                parsed["signal_dbm"] = float(match.group(1))
        elif line.startswith("rx bitrate:"):
            parsed["rx_bitrate"] = line.split(":", 1)[1].strip()
        elif line.startswith("tx bitrate:"):
            parsed["tx_bitrate"] = line.split(":", 1)[1].strip()
        elif line.startswith("RX:"):
            match = re.search(r"(\d+) bytes", line)
            if match:
                parsed["rx_bytes"] = int(match.group(1))
        elif line.startswith("TX:"):
            match = re.search(r"(\d+) bytes", line)
            if match:
                parsed["tx_bytes"] = int(match.group(1))
    return parsed


def get_wlan_link(iface: str, namespace: str | None = None) -> dict[str, Any]:
    """Return the wireless association for ``iface`` using ``iw link``."""
    iface = validate_interface_name(iface)
    log.debug("get_wlan_link iface=%s namespace=%r", iface, namespace)
    try:
        result = ns_exec([IW_FILE, "dev", iface, "link"], namespace=namespace)
    except RunCommandError as exc:
        log.error("iw link failed for %s: %r", iface, exc)
        raise

    parsed = _parse_iw_link(result.stdout)
    return {
        "interface": iface,
        "namespace": namespace,
        "connected": parsed.get("connected", False),
        "ssid": parsed.get("ssid"),
        "bssid": parsed.get("bssid"),
        "freq_mhz": parsed.get("freq_mhz"),
        "signal_dbm": parsed.get("signal_dbm"),
        "rx_bitrate": parsed.get("rx_bitrate"),
        "tx_bitrate": parsed.get("tx_bitrate"),
        "rx_bytes": parsed.get("rx_bytes"),
        "tx_bytes": parsed.get("tx_bytes"),
        "raw": result.stdout,
    }
