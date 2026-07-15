"""Per-interface link statistics via ethtool."""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from wlanpi_core.constants import ETHTOOL_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec
from wlanpi_core.utils.validation import validate_interface_name

log = logging.getLogger(__name__)


def _parse_ethtool(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        normalized = key.strip().lower().replace(" ", "_")
        parsed[normalized] = value.strip()
    return parsed


def get_link_stats(iface: str, namespace: Optional[str] = None) -> dict[str, Any]:
    """Return link statistics for ``iface`` using ethtool."""
    iface = validate_interface_name(iface)
    log.debug("get_link_stats iface=%s namespace=%r", iface, namespace)
    try:
        result = ns_exec([ETHTOOL_FILE, iface], namespace=namespace)
        raw = _parse_ethtool(result.stdout)
        speed_match = re.search(r"(\d+)", raw.get("speed", ""))
        return {
            "interface": iface,
            "namespace": namespace,
            "link_detected": raw.get("link_detected"),
            "speed_mbps": int(speed_match.group(1)) if speed_match else None,
            "duplex": raw.get("duplex"),
            "port": raw.get("port"),
            "driver": raw.get("driver"),
            "raw": raw,
        }
    except RunCommandError as exc:
        log.error("ethtool failed for %s: %r", iface, exc)
        raise
