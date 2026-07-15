"""Reachability and ping helpers for utils API."""
from __future__ import annotations

import ipaddress
import re
from typing import Any, Optional

from wlanpi_core.constants import REACHABILITY_MAX_CUSTOM_TARGETS
from wlanpi_core.utils.general import run_command_async

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


def validate_ping_target(target: str) -> str:
    """Validate a hostname or IP safe for ping subprocess."""
    target = target.strip()
    if not target:
        raise ValueError("target must not be empty")
    try:
        ipaddress.ip_address(target)
        return target
    except ValueError:
        pass
    if _HOSTNAME_RE.fullmatch(target):
        return target
    raise ValueError(f"invalid ping target: {target}")


def parse_targets_param(targets: Optional[list[str]]) -> list[str]:
    """Normalize repeated or comma-separated ``targets`` query values."""
    if not targets:
        return []

    parsed: list[str] = []
    for raw in targets:
        for part in raw.split(","):
            part = part.strip()
            if part:
                parsed.append(validate_ping_target(part))

    if len(parsed) > REACHABILITY_MAX_CUSTOM_TARGETS:
        raise ValueError(
            f"at most {REACHABILITY_MAX_CUSTOM_TARGETS} custom targets allowed"
        )

    # Preserve order while deduplicating.
    seen: set[str] = set()
    unique: list[str] = []
    for target in parsed:
        key = target.lower()
        if key not in seen:
            seen.add(key)
            unique.append(target)
    return unique


def ping_stats_from_jc(data: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Build API ping stats from ``jc ping`` JSON."""
    if not data:
        return {
            "success": False,
            "rttMsMin": None,
            "rttMsAvg": None,
            "rttMsMax": None,
            "packetLossPercent": None,
            "display": "FAIL",
        }

    received = data.get("packets_received") or 0
    success = received > 0
    avg = data.get("round_trip_ms_avg")
    display = f"{avg}ms" if success and avg is not None else "FAIL"
    return {
        "success": success,
        "rttMsMin": data.get("round_trip_ms_min"),
        "rttMsAvg": avg,
        "rttMsMax": data.get("round_trip_ms_max"),
        "packetLossPercent": data.get("packet_loss_percent"),
        "display": display,
    }


async def ping_target(target: str) -> dict[str, Any]:
    """Ping one target and return structured stats."""
    target = validate_ping_target(target)
    result = await run_command_async(
        ["jc", "ping", "-c1", "-W2", "-q", target],
        raise_on_fail=False,
    )
    stats = ping_stats_from_jc(result.output_from_json())
    stats["target"] = target
    return stats
