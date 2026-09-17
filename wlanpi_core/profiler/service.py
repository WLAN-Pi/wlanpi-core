"""Profiler beaconing status helpers."""

import os
from typing import Any


def get_status() -> dict[str, Any]:
    """Return the profiler status and beaconing SSID."""
    running = profiler_beaconing()
    ssid = profiler_beaconing_ssid()

    return {
        "running": running,
        "ssid": ssid,
        "passphrase": "12345678" if running else None,
    }


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
