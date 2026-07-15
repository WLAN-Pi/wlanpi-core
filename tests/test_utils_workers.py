"""Unit tests for reachability and speedtest helpers."""

from unittest.mock import AsyncMock, patch

import pytest

from wlanpi_core.constants import LIBRESPEED_CLI, SPEEDTEST_TIMEOUT_SEC
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.utils.reachability import (
    parse_targets_param,
    ping_stats_from_jc,
    validate_ping_target,
)
from wlanpi_core.utils.speedtest import parse_librespeed_output, run_speedtest

SAMPLE_LIBRESPEED = """\
Retrieving server list from https://librespeed.org/backend-servers/servers.php
Selecting the fastest server based on ping
Ping:\t5.00 ms\tJitter:\t0.00 ms
Download rate:\t495.79 Mbps
Upload rate:\t690.97 Mbps
[{"timestamp":"2026-06-14T18:38:48.994139018+01:00","server":{"name":"London, England (Clouvider)","url":"https://lon.speedtest.clouvider.net/backend"},"client":{"ip":"217.155.247.50","hostname":"","city":"","region":"","country":"","loc":"","org":"","postal":"","timezone":""},"bytes_sent":1347584000,"bytes_received":966920456,"ping":5,"jitter":0,"upload":690.97,"download":495.79,"share":""}]
"""

JC_PING_OK = {
    "packets_received": 1,
    "round_trip_ms_min": 5.17,
    "round_trip_ms_avg": 5.17,
    "round_trip_ms_max": 5.17,
    "packet_loss_percent": 0.0,
}


def test_validate_ping_target_accepts_ip_and_hostname():
    assert validate_ping_target("8.8.8.8") == "8.8.8.8"
    assert validate_ping_target("cloudflare.com") == "cloudflare.com"


def test_validate_ping_target_rejects_unsafe_input():
    with pytest.raises(ValueError, match="invalid ping target"):
        validate_ping_target("8.8.8.8; reboot")


def test_parse_targets_param_supports_comma_and_repeat():
    assert parse_targets_param(["8.8.8.8,1.1.1.1", "cloudflare.com"]) == [
        "8.8.8.8",
        "1.1.1.1",
        "cloudflare.com",
    ]


def test_parse_targets_param_enforces_limit():
    with pytest.raises(ValueError, match="at most"):
        parse_targets_param([",".join(f"10.0.0.{i}" for i in range(1, 12))])


def test_ping_stats_from_jc_success():
    stats = ping_stats_from_jc(JC_PING_OK)
    assert stats["success"] is True
    assert stats["display"] == "5.17ms"
    assert stats["rttMsAvg"] == 5.17


def test_ping_stats_from_jc_failure():
    stats = ping_stats_from_jc(None)
    assert stats["success"] is False
    assert stats["display"] == "FAIL"


def test_parse_librespeed_output_extracts_speeds():
    result = parse_librespeed_output(SAMPLE_LIBRESPEED)
    assert result["ipAddress"] == "217.155.247.50"
    assert result["downloadSpeed"] == "495.79 Mbps"
    assert result["uploadSpeed"] == "690.97 Mbps"
    assert result["pingMs"] == 5
    assert result["server"] == "London, England (Clouvider)"
    assert result["testedAt"] is not None


@pytest.mark.asyncio
async def test_run_speedtest_uses_async_command_timeout():
    command_result = CommandResult(SAMPLE_LIBRESPEED, "", 0)
    with patch(
        "wlanpi_core.utils.speedtest.run_command_async",
        new=AsyncMock(return_value=command_result),
    ) as command:
        result = await run_speedtest()

    command.assert_awaited_once_with(
        [LIBRESPEED_CLI, "--json", "--simple"],
        raise_on_fail=False,
        timeout=SPEEDTEST_TIMEOUT_SEC,
    )
    assert result["downloadSpeed"] == "495.79 Mbps"
