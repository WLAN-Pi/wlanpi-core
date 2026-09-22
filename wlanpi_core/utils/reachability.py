"""Reachability and ping helpers for utils API."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

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


def parse_targets_param(targets: list[str] | None) -> list[str]:
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


def ping_stats_from_jc(data: dict[str, Any] | None) -> dict[str, Any]:
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
        # ponytail: -4 because hostnames otherwise resolve to IPv6 first and
        # fail on IPv4-only links (the old reachability.sh used -4 too).
        # Ceiling: IPv6 targets unsupported. Upgrade: pick the family per target.
        ["jc", "ping", "-c1", "-W2", "-q", "-4", target],
        raise_on_fail=False,
    )
    parsed = result.output_from_json()
    stats = ping_stats_from_jc(parsed if isinstance(parsed, dict) else None)
    stats["target"] = target
    return stats
