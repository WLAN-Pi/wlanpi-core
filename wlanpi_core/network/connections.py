"""Active TCP/UDP socket listings via ss."""
from __future__ import annotations

import logging
from typing import Any, Optional

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def _parse_ss_line(line: str, protocol: str) -> Optional[dict[str, Any]]:
    parts = line.split()
    if len(parts) < 5:
        return None
    state, recv_q, send_q, local, peer = parts[0], parts[1], parts[2], parts[3], parts[4]
    return {
        "protocol": protocol,
        "state": state,
        "recv_q": int(recv_q) if recv_q.isdigit() else recv_q,
        "send_q": int(send_q) if send_q.isdigit() else send_q,
        "local": local,
        "peer": peer,
    }


def _get_connections(protocol: str, namespace: Optional[str] = None) -> dict[str, Any]:
    flag = "t" if protocol == "tcp" else "u"
    log.debug("get_%s_connections namespace=%r", protocol, namespace)
    try:
        result = ns_exec(
            ["ss", f"-H{flag}n", "state", "all"],
            namespace=namespace,
        )
        connections = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            entry = _parse_ss_line(line, protocol)
            if entry:
                connections.append(entry)
        return {"namespace": namespace, "connections": connections}
    except RunCommandError as exc:
        log.error("ss failed for %s: %r", protocol, exc)
        raise


def get_tcp_connections(namespace: Optional[str] = None) -> dict[str, Any]:
    return _get_connections("tcp", namespace=namespace)


def get_udp_connections(namespace: Optional[str] = None) -> dict[str, Any]:
    return _get_connections("udp", namespace=namespace)
