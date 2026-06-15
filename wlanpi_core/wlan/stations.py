"""AP-mode station parsing for hotspot endpoints."""
from __future__ import annotations

import re
from typing import Any, Optional

from wlanpi_core.constants import IW_FILE
from wlanpi_core.core.mode_guard import require_mode
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services.hotspot_service import resolve_ap_interface
from wlanpi_core.utils.general import run_command

_STATION_HEADER = re.compile(
    r"^Station\s+(?P<mac>[0-9a-f:]+)\s+\(on\s+(?P<iface>\S+)\)",
    re.IGNORECASE,
)
_KV_LINE = re.compile(r"^\s+(?P<key>[^:]+):\s+(?P<value>.+)$")


def _parse_station_blocks(output: str) -> list[dict[str, Any]]:
    stations: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in output.splitlines():
        header = _STATION_HEADER.match(line)
        if header:
            if current:
                stations.append(current)
            current = {
                "mac": header.group("mac").lower(),
                "interface": header.group("iface"),
            }
            continue
        if current is None:
            continue
        match = _KV_LINE.match(line)
        if not match:
            continue
        key = match.group("key").strip().lower().replace(" ", "_").replace("/", "_")
        value = match.group("value").strip()
        if key == "signal":
            signal_match = re.search(r"-?\d+", value)
            current["signal_dbm"] = int(signal_match.group(0)) if signal_match else None
            continue
        if key in ("tx_bitrate", "rx_bitrate"):
            current[key] = value
            continue
        current[key] = value

    if current:
        stations.append(current)

    return stations


def _station_dump(iface: str) -> str:
    try:
        return run_command(
            [IW_FILE, "dev", iface, "station", "dump"],
            raise_on_fail=True,
        ).stdout
    except (RunCommandError, FileNotFoundError) as exc:
        raise ValidationError(
            f"Unable to read station list: {exc}", status_code=503
        ) from exc


def get_hotspot_stations(iface: Optional[str] = None) -> dict[str, Any]:
    require_mode("hotspot")
    ap_iface = resolve_ap_interface(iface)
    stations = _parse_station_blocks(_station_dump(ap_iface))
    return {
        "mode": "hotspot",
        "interface": ap_iface,
        "count": len(stations),
        "stations": stations,
    }


def get_hotspot_client_link(iface: Optional[str] = None) -> dict[str, Any]:
    """
    Per-station link statistics for the hotspot AP interface.

    Returns the same station entries as ``get_hotspot_stations`` with link-focused
    fields promoted for UI consumption.
    """
    payload = get_hotspot_stations(iface=iface)
    links = []
    for station in payload["stations"]:
        links.append(
            {
                "mac": station.get("mac"),
                "interface": station.get("interface"),
                "signal_dbm": station.get("signal_dbm"),
                "tx_bitrate": station.get("tx_bitrate"),
                "rx_bitrate": station.get("rx_bitrate"),
                "inactive_time": station.get("inactive_time"),
                "connected_time": station.get("connected_time"),
                "authorized": station.get("authorized"),
                "authenticated": station.get("authenticated"),
                "associated": station.get("associated"),
            }
        )
    return {
        "mode": payload["mode"],
        "interface": payload["interface"],
        "count": payload["count"],
        "links": links,
    }
