"""Profiler beaconing status helpers."""

import json
import os
from typing import Any

INFO_FILE = "/run/wlanpi-profiler.info.json"


def get_status() -> dict[str, Any]:
    """Return the profiler status and beaconing SSID."""
    running = profiler_beaconing()
    ssid = profiler_beaconing_ssid()

    return {
        "running": running,
        "ssid": ssid,
        "passphrase": _profiler_passphrase() if running else None,
    }


def _profiler_info() -> dict[str, Any]:
    """Read the profiler info file, or an empty mapping when unavailable."""
    try:
        with open(INFO_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _profiler_passphrase() -> str | None:
    """Return the passphrase the profiler is actually using, if any."""
    value = _profiler_info().get("passphrase")
    return value if isinstance(value, str) and value else None


def profiler_beaconing() -> bool:
    """Check whether the Profiler is beaconing.

    Probes the presence of /var/run/wlanpi-profiler.ssid.
    """
    ssid_file = "/var/run/wlanpi-profiler.ssid"
    if os.path.exists(ssid_file):
        return True
    else:
        return False


def profiler_beaconing_ssid() -> str | None:
    """Return the SSID currently in use by the Profiler."""
    ssid_file = "/var/run/wlanpi-profiler.ssid"
    if os.path.exists(ssid_file):
        with open(ssid_file) as f:
            return f.read()
    return None
