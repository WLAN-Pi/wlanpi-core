"""Tests for the /system/ntp clock/NTP state."""

import asyncio
from unittest.mock import AsyncMock

from wlanpi_core.api.api_v1.endpoints import system_api
from wlanpi_core.services import system_service

SHOW = "NTP=yes\nNTPSynchronized=no\n"
SHOW_TIMESYNC = (
    "FallbackNTPServers=0.debian.pool.ntp.org 1.debian.pool.ntp.org\n"
    "ServerName=2.debian.pool.ntp.org\n"
    "ServerAddress=192.168.2.123\n"
    "PollIntervalUSec=32s\n"
    "Frequency=-1234\n"
)


class _Result:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def _fake_run(stdout_show: str, stdout_timesync: str, stdout_runtime: str = "as 0"):
    def _run(cmd, **_kwargs):
        if cmd[:2] == ["timedatectl", "show"]:
            return _Result(stdout_show)
        if cmd[:2] == ["timedatectl", "show-timesync"]:
            return _Result(stdout_timesync)
        if cmd[0] == "busctl":
            return _Result(stdout_runtime)
        raise AssertionError(f"unexpected command: {cmd}")

    return _run


def test_get_ntp_parses_state(monkeypatch):
    monkeypatch.setattr(system_service, "run_command", _fake_run(SHOW, SHOW_TIMESYNC))

    result = system_service.get_ntp()

    assert result["ntp_service"] is True
    assert result["synchronized"] is False
    assert result["server_name"] == "2.debian.pool.ntp.org"
    assert result["server_address"] == "192.168.2.123"
    assert result["fallback_servers"] == [
        "0.debian.pool.ntp.org",
        "1.debian.pool.ntp.org",
    ]
    assert result["poll_interval"] == "32s"
    assert result["frequency"] == -1234
    assert result["runtime_servers"] == []
    assert result["source"] == "default"


def test_get_ntp_source_dhcp_when_runtime_servers(monkeypatch):
    monkeypatch.setattr(
        system_service,
        "run_command",
        _fake_run(SHOW, SHOW_TIMESYNC, stdout_runtime='as 1 "192.168.2.123"'),
    )

    result = system_service.get_ntp()

    assert result["runtime_servers"] == ["192.168.2.123"]
    assert result["source"] == "dhcp"


def test_get_ntp_unknown_when_no_servers(monkeypatch):
    monkeypatch.setattr(
        system_service, "run_command", _fake_run("NTP=no\nNTPSynchronized=no\n", "")
    )

    result = system_service.get_ntp()

    assert result["server_name"] is None
    assert result["server_address"] is None
    assert result["fallback_servers"] == []
    assert result["poll_interval"] is None
    assert result["source"] == "unknown"


def test_get_ntp_tolerates_command_failure(monkeypatch):
    def _boom(cmd, **_kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(system_service, "run_command", _boom)

    result = system_service.get_ntp()

    assert result["synchronized"] is False
    assert result["ntp_service"] is False
    assert result["runtime_servers"] == []
    assert result["source"] == "unknown"


def test_ntp_endpoint_uses_to_thread(mocker):
    to_thread = mocker.patch.object(
        system_api.asyncio,
        "to_thread",
        new=AsyncMock(return_value={"synchronized": True}),
    )

    result = asyncio.run(system_api.show_ntp())

    to_thread.assert_awaited_once_with(system_service.get_ntp)
    assert result == {"synchronized": True}
