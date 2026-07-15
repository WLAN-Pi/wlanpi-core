import asyncio
from unittest.mock import AsyncMock, call

import pytest

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.streaming import connection_manager
from wlanpi_core.streaming.connection_manager import ConnectionManager


class BlockingStdout:
    async def read(self, size):
        await asyncio.Event().wait()


class CaptureProcess:
    def __init__(self):
        self.returncode = None
        self.stdout = BlockingStdout()
        self.terminated = False
        self.killed = False
        self._finished = asyncio.Event()

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self._finished.set()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self._finished.set()

    async def wait(self):
        await self._finished.wait()
        return self.returncode


def _connected_client(manager, websocket):
    manager.clients[websocket] = {
        "configs": {},
        "proc": None,
        "task": None,
        "channel_tasks": {},
    }


@pytest.mark.asyncio
async def test_supported_frequencies_uses_bounded_async_commands(mocker):
    manager = ConnectionManager()
    websocket = object()
    run_command = mocker.patch.object(
        connection_manager,
        "run_command_async",
        new=AsyncMock(
            side_effect=[
                CommandResult("Interface wlanpi0\n", "", 0),
                CommandResult("* 2412 MHz\n* 2437 MHz (disabled)\n", "", 0),
            ]
        ),
    )
    send_event = mocker.patch.object(manager, "send_event", new=AsyncMock())

    await manager.send_supported_frequencies(websocket)

    assert run_command.await_args_list == [
        call(
            [connection_manager.IW_FILE, "dev"],
            timeout=connection_manager._IW_TIMEOUT_SEC,
        ),
        call(
            [connection_manager.IW_FILE, "phy", "phy0", "channels"],
            timeout=connection_manager._IW_TIMEOUT_SEC,
        ),
    ]
    send_event.assert_awaited_once_with(
        websocket,
        "frequencies",
        "SUPPORTED_FREQUENCIES",
        {"wlanpi0": [2412]},
    )


@pytest.mark.asyncio
async def test_set_channel_uses_bounded_async_command(mocker):
    manager = ConnectionManager()
    run_command = mocker.patch.object(
        connection_manager,
        "run_command_async",
        new=AsyncMock(return_value=CommandResult("", "", 0)),
    )

    assert await manager._set_channel("wlanpi0", 5180, 20) is True

    run_command.assert_awaited_once_with(
        [connection_manager.IW_FILE, "dev", "wlanpi0", "set", "freq", "5180", "20"],
        raise_on_fail=False,
        timeout=connection_manager._IW_TIMEOUT_SEC,
    )


@pytest.mark.asyncio
async def test_capture_process_is_isolated_and_reaped_on_stop(mocker):
    manager = ConnectionManager()
    websocket = object()
    _connected_client(manager, websocket)
    process = CaptureProcess()
    create_process = mocker.patch.object(
        connection_manager.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(return_value=process),
    )
    mocker.patch.object(manager, "send_message_event", new=AsyncMock())
    manager.configure(websocket, "wlanpi0", {})

    await manager.start_streaming(websocket, ["wlanpi0"], "")

    create_process.assert_awaited_once_with(
        connection_manager.DUMPCAP_FILE,
        "-i",
        "wlanpi0",
        "-q",
        "-t",
        "-w",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )

    await manager.stop_streaming(websocket)

    assert process.terminated is True
    assert process.returncode == -15
    assert manager.clients[websocket]["proc"] is None
    assert manager.clients[websocket]["task"] is None


@pytest.mark.asyncio
async def test_second_capture_does_not_orphan_first_process(mocker):
    manager = ConnectionManager()
    websocket = object()
    running_task = mocker.Mock()
    running_task.done.return_value = False
    manager.clients[websocket] = {
        "configs": {},
        "proc": CaptureProcess(),
        "task": running_task,
        "channel_tasks": {},
    }
    create_process = mocker.patch.object(
        connection_manager.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(),
    )
    send_event = mocker.patch.object(
        manager,
        "send_message_event",
        new=AsyncMock(),
    )

    await manager.start_streaming(websocket, ["wlanpi0"], "")

    create_process.assert_not_awaited()
    send_event.assert_awaited_once_with(
        websocket,
        "error",
        "CAPTURE_ALREADY_RUNNING",
        "A capture is already running for this client.",
    )


@pytest.mark.asyncio
async def test_capture_rejects_missing_interface_config_before_process(mocker):
    manager = ConnectionManager()
    websocket = object()
    _connected_client(manager, websocket)
    create_process = mocker.patch.object(
        connection_manager.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(),
    )
    send_event = mocker.patch.object(
        manager,
        "send_message_event",
        new=AsyncMock(),
    )

    await manager.start_streaming(websocket, ["wlanpi0"], "")

    create_process.assert_not_awaited()
    send_event.assert_awaited_once_with(
        websocket,
        "error",
        "CONFIG_MISSING",
        "No config for: wlanpi0",
    )


@pytest.mark.parametrize(
    "config",
    [
        {"dwell_time": 1},
        {"channels": [{"freq": 2412, "width": 10}]},
        {"channels": [{"freq": 99999, "width": 20}]},
        {"unknown": True},
    ],
)
def test_capture_rejects_unsafe_interface_configuration(config):
    manager = ConnectionManager()
    websocket = object()
    _connected_client(manager, websocket)

    with pytest.raises(ValueError):
        manager.configure(websocket, "wlanpi0", config)

    assert manager.clients[websocket]["configs"] == {}


@pytest.mark.asyncio
async def test_capture_rejects_invalid_start_before_process(mocker):
    manager = ConnectionManager()
    websocket = object()
    _connected_client(manager, websocket)
    create_process = mocker.patch.object(
        connection_manager.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(),
    )
    send_event = mocker.patch.object(
        manager,
        "send_message_event",
        new=AsyncMock(),
    )

    await manager.start_streaming(websocket, ["--help"], "tcp\nport 22")

    create_process.assert_not_awaited()
    send_event.assert_awaited_once_with(
        websocket,
        "error",
        "CAPTURE_CONFIG_INVALID",
        "Invalid capture start configuration.",
    )


@pytest.mark.asyncio
async def test_set_channel_rejects_invalid_center_before_command(mocker):
    manager = ConnectionManager()
    run_command = mocker.patch.object(
        connection_manager,
        "run_command_async",
        new=AsyncMock(),
    )

    assert await manager._set_channel("wlanpi0", 5000, 160) is False
    run_command.assert_not_awaited()
