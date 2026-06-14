"""Resolve which network namespace owns an interface."""
from __future__ import annotations

import logging
from typing import Optional

from wlanpi_core.utils import network_config

log = logging.getLogger(__name__)


def resolve_interface_namespace(iface: str) -> Optional[str]:
    """
    Return the namespace containing ``iface``, or None for root.

    Uses ``network_config.status()`` (same view as ``GET /network/config/status``).
    """
    iface = iface.strip()
    if not iface:
        return None

    try:
        status = network_config.status()
    except Exception as exc:
        log.warning("Could not read namespace status for %s: %r", iface, exc)
        return None

    root_status = status.get("root") or {}
    if "error" not in root_status and iface in root_status:
        return None

    for ns_name, ns_status in status.items():
        if ns_name == "root" or not isinstance(ns_status, dict):
            continue
        if "error" in ns_status:
            continue
        if iface in ns_status:
            return ns_name

    return None
