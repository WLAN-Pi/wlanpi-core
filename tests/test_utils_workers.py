"""Unit tests for reachability and speedtest helpers."""

from datetime import UTC, datetime
from pathlib import Path
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

SAMPLE_LIBRESPEED = (
    Path(__file__).parent / "fixtures/librespeed-cli/v1.0.10-linux-arm64.stdout"
).read_text()

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


def test_get_default_gateways_extracts_interface_name():
    from wlanpi_core.utils import network as network_utils

    output = (
        "default via 192.168.6.1 dev eth0 proto dhcp src 192.168.6.63 metric 100\n"
        "default via 10.0.0.1 dev wlan0 proto dhcp metric 600\n"
    )
    with patch.object(
        network_utils, "run_command", return_value=CommandResult(output, "", 0)
    ):
        assert network_utils.get_default_gateways() == {
            "eth0": "192.168.6.1",
            "wlan0": "10.0.0.1",
        }


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
    assert result == {
        "ipAddress": "",
        "downloadSpeed": "790.68 Mbps",
        "uploadSpeed": "126.37 Mbps",
        "pingMs": 17,
        "jitterMs": 0.04,
        "server": "New York, United States (2) (Clouvider)",
        "testedAt": datetime(2026, 9, 22, 20, 42, 22, 896290, tzinfo=UTC),
    }


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
    assert result["downloadSpeed"] == "790.68 Mbps"
