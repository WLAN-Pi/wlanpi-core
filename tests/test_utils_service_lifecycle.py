import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.services import utils_service
from wlanpi_core.utils import reachability, speedtest


def test_read_dns_servers_ignores_malformed_lines(tmp_path):
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.write_text(
        "nameserver\nsearch example.test\nnameserver 1.1.1.1 extra\n"
    )

    assert utils_service._read_dns_servers(str(resolv_conf)) == ["1.1.1.1"]


@pytest.mark.asyncio
async def test_reachability_handles_invalid_ping_json(monkeypatch):
    monkeypatch.setattr(
        utils_service,
        "get_default_gateways",
        lambda: {"eth0": "192.0.2.1"},
    )
    monkeypatch.setattr(utils_service, "_read_dns_servers", lambda: ["1.1.1.1"])

    async def run_command(cmd, **_kwargs):
        if cmd[0] == "curl":
            return CommandResult("google.com", "", 0)
        if cmd[0] == "arping":
            return CommandResult("1.25ms", "", 0)
        if cmd[0] == "dig":
            return CommandResult("ns1.example.test", "", 0)
        return CommandResult("not JSON", "", 0)

    monkeypatch.setattr(utils_service, "run_command_async", run_command)

    result = await utils_service.show_reachability()

    assert result["results"]["Ping Google"] == "FAIL"
    assert result["results"]["Ping Gateway"] == "FAIL"
    assert result["results"]["Browse Google"] == "OK"
    assert result["results"]["Arping Gateway"] == "1.25ms"


@pytest.mark.asyncio
async def test_reachability_cancels_every_child_task(monkeypatch):
    monkeypatch.setattr(
        utils_service,
        "get_default_gateways",
        lambda: {"eth0": "192.0.2.1"},
    )
    monkeypatch.setattr(utils_service, "_read_dns_servers", lambda: ["1.1.1.1"])
    started = 0
    cancelled = 0
    all_started = asyncio.Event()

    async def blocked_command(*_args, **_kwargs):
        nonlocal started, cancelled
        started += 1
        if started == 5:
            all_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled += 1

    monkeypatch.setattr(utils_service, "run_command_async", blocked_command)
    task = asyncio.create_task(utils_service.show_reachability())
    await asyncio.wait_for(all_started.wait(), timeout=2)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled == 5


@pytest.mark.asyncio
async def test_show_usb_returns_serializable_error(monkeypatch):
    monkeypatch.setattr(
        utils_service,
        "run_command_async",
        AsyncMock(side_effect=RunCommandError("lsusb failed", 1)),
    )

    result = await utils_service.show_usb()

    assert result == {
        "error": {"error": "Issue getting usb info using lsusb command: lsusb failed"}
    }
    json.dumps(result)


@pytest.mark.asyncio
async def test_show_ufw_returns_error_response(monkeypatch):
    monkeypatch.setattr(utils_service.os.path, "isfile", lambda _path: True)
    monkeypatch.setattr(
        utils_service,
        "run_command_async",
        AsyncMock(side_effect=RunCommandError("ufw failed", 1)),
    )

    result = await utils_service.show_ufw()

    assert result == {
        "error": {"error": "Issue getting ufw info using ufw command"}
    }


@pytest.mark.asyncio
async def test_speedtest_missing_executable_is_scoped_failure(monkeypatch):
    monkeypatch.setattr(
        speedtest,
        "run_command_async",
        AsyncMock(side_effect=FileNotFoundError("librespeed-cli")),
    )

    with pytest.raises(RuntimeError, match="LibreSpeed CLI is unavailable"):
        await speedtest.run_speedtest()


@pytest.mark.asyncio
async def test_ping_target_validates_its_input(monkeypatch):
    command = AsyncMock()
    monkeypatch.setattr(reachability, "run_command_async", command)

    with pytest.raises(ValueError, match="invalid ping target"):
        await reachability.ping_target("example.com; reboot")

    command.assert_not_awaited()
