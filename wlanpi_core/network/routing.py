"""Routing table queries."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from wlanpi_core.constants import IP_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def get_routing_table(namespace: Optional[str] = None) -> dict[str, Any]:
    """Return the IPv4/IPv6 routing table as structured JSON."""
    log.debug("get_routing_table namespace=%r", namespace)
    try:
        result = ns_exec([IP_FILE, "-j", "route", "show"], namespace=namespace)
        routes = json.loads(result.stdout) if result.stdout.strip() else []
        if not isinstance(routes, list):
            routes = [routes]
        return {"namespace": namespace, "routes": routes}
    except RunCommandError as exc:
        log.error("Failed to read routing table: %r", exc)
        raise
