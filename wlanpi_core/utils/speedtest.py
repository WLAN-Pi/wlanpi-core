"""LibreSpeed speedtest helpers for utils API."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from wlanpi_core.constants import LIBRESPEED_CLI, SPEEDTEST_TIMEOUT_SEC
from wlanpi_core.utils.general import run_command_async


def parse_librespeed_output(stdout: str) -> dict[str, Any]:
    """Parse ``librespeed-cli --json --simple`` output."""
    payload: Optional[list[dict[str, Any]]] = None
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list) and parsed:
            payload = parsed
            break

    if not payload:
        raise ValueError("speedtest output did not contain JSON results")

    row = payload[0]
    download = row.get("download")
    upload = row.get("upload")
    client = row.get("client") or {}
    ip_address = client.get("ip") or ""

    if not ip_address:
        processed = row.get("processedString") or ""
        match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", processed)
        if match:
            ip_address = match.group(1)

    tested_at = row.get("timestamp")
    if tested_at:
        try:
            normalized = re.sub(r"(\.\d{6})\d+", r"\1", tested_at)
            tested_at = datetime.fromisoformat(normalized).astimezone(timezone.utc)
        except ValueError:
            tested_at = None
    else:
        tested_at = None

    server = (row.get("server") or {}).get("name")

    return {
        "ipAddress": ip_address,
        "downloadSpeed": f"{download:.2f} Mbps" if download is not None else "FAIL",
        "uploadSpeed": f"{upload:.2f} Mbps" if upload is not None else "FAIL",
        "pingMs": row.get("ping"),
        "jitterMs": row.get("jitter"),
        "server": server,
        "testedAt": tested_at,
    }


async def run_speedtest() -> dict[str, Any]:
    """Run LibreSpeed CLI and return parsed results."""
    result = await run_command_async(
        [LIBRESPEED_CLI, "--json", "--simple"],
        raise_on_fail=False,
        timeout=SPEEDTEST_TIMEOUT_SEC,
    )
    if not result.success:
        detail = (result.stderr or result.stdout or "speedtest failed").strip()
        raise RuntimeError(detail)
    return parse_librespeed_output(result.stdout)
