"""Unit tests for blinker and bluetooth pair services."""

import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest

from wlanpi_core.services import bluetooth_service, utils_service


def test_port_blinker_status_not_running(mocker):
    run = mocker.patch.object(
        utils_service.subprocess,
        "run",
        return_value=MagicMock(returncode=1, stdout=""),
    )
    assert utils_service.port_blinker_status() == {"active": False}
    run.assert_called_once_with(
        ["pidof", "-x", "portblinker.sh"],
        capture_output=True,
        text=True,
        check=False,
        timeout=utils_service._BLINKER_CONTROL_TIMEOUT_SEC,
    )


def test_start_port_blinker_missing_script(mocker, tmp_path):
    mocker.patch.object(utils_service, "BLINKER_FILE", str(tmp_path / "missing.sh"))
    mocker.patch.object(utils_service, "_blinker_script_running", return_value=False)
    with pytest.raises(FileNotFoundError):
        utils_service.start_port_blinker()


def test_start_port_blinker_isolates_process_group(mocker, tmp_path):
    script = tmp_path / "portblinker.sh"
    script.touch()
    mocker.patch.object(utils_service, "BLINKER_FILE", str(script))
    mocker.patch.object(utils_service, "_blinker_script_running", return_value=False)
    popen = mocker.patch.object(utils_service.subprocess, "Popen")
    utils_service._blinker_process = None

    assert utils_service.start_port_blinker("eth0")["status"] == "started"

    popen.assert_called_once_with(
        [str(script), "-i", "eth0", "--no-color"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    utils_service._blinker_process = None


def test_stop_port_blinker_terminates_owned_process(mocker):
    process = MagicMock()
    process.poll.return_value = None
    utils_service._blinker_process = process
    terminate = mocker.patch.object(utils_service, "terminate_process")
    mocker.patch.object(utils_service, "_blinker_script_running", return_value=False)

    assert utils_service.stop_port_blinker() == {
        "active": False,
        "status": "stopped",
    }

    terminate.assert_called_once_with(process)
    assert utils_service._blinker_process is None


def test_stop_unowned_blinker_bounds_control_commands(mocker):
    running = mocker.patch.object(
        utils_service,
        "_blinker_script_running",
        side_effect=[True, False],
    )
    run = mocker.patch.object(utils_service.subprocess, "run")

    assert utils_service.stop_port_blinker() == {
        "active": False,
        "status": "stopped",
    }

    run.assert_called_once_with(
        ["pkill", "-TERM", "-f", "portblinker.sh"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=utils_service._BLINKER_CONTROL_TIMEOUT_SEC,
    )
    assert running.call_count == 2


def test_bluetooth_paired_devices_uses_bluez_devices_filter(mocker):
    mocker.patch.object(bluetooth_service, "bluetooth_present", return_value=True)
    run_command = mocker.patch.object(
        bluetooth_service,
        "run_command",
        return_value=MagicMock(stdout="Device aa:bb:cc:dd:ee:ff Test Phone\n"),
    )

    assert bluetooth_service.bluetooth_paired_devices() == {
        "AA:BB:CC:DD:EE:FF": "Test Phone"
    }
    run_command.assert_called_once_with(
        cmd=["bluetoothctl", "devices", "Paired"], raise_on_fail=True
    )


@pytest.mark.asyncio
async def test_bluetooth_pair_discoverable(mocker):
    mocker.patch.object(
        bluetooth_service, "_bluetooth_present_async", new=AsyncMock(return_value=True)
    )
    mocker.patch.object(bluetooth_service, "_ensure_bluetooth_powered", new=AsyncMock())
    mocker.patch.object(
        bluetooth_service,
        "_bluetooth_alias_async",
        new=AsyncMock(return_value="wlanpi-test"),
    )
    mocker.patch.object(bluetooth_service, "_unpair_all_devices", new=AsyncMock())
    mocker.patch.object(
        bluetooth_service,
        "_pairing_mode_active",
        new=AsyncMock(side_effect=[False, True]),
    )
    run_command = mocker.patch.object(
        bluetooth_service,
        "run_command_async",
        new=AsyncMock(return_value=MagicMock(success=True)),
    )

    result = await bluetooth_service.bluetooth_pair()
    assert result["status"] == "discoverable"
    assert result["alias"] == "wlanpi-test"
    run_command.assert_awaited_once_with(
        ["systemctl", "start", "bt-timedpair.service"],
        raise_on_fail=True,
        timeout=bluetooth_service.BLUETOOTH_PAIRING_START_TIMEOUT_SEC,
    )


@pytest.mark.asyncio
async def test_unpair_all_devices_uses_argv_and_rechecks(mocker):
    paired_devices = mocker.patch.object(
        bluetooth_service,
        "_bluetooth_paired_devices_async",
        new=AsyncMock(side_effect=[{"AA:BB:CC:DD:EE:FF": "Test Phone"}, {}]),
    )
    run_command = mocker.patch.object(
        bluetooth_service,
        "run_command_async",
        new=AsyncMock(return_value=MagicMock(success=True)),
    )
    mocker.patch.object(bluetooth_service.asyncio, "sleep", new=AsyncMock())

    await bluetooth_service._unpair_all_devices(timeout_sec=30)

    run_command.assert_awaited_once()
    assert run_command.await_args.args[0] == [
        "bluetoothctl",
        "remove",
        "AA:BB:CC:DD:EE:FF",
    ]
    assert paired_devices.await_count == 2


@pytest.mark.asyncio
async def test_unpair_all_devices_raises_at_deadline():
    with pytest.raises(bluetooth_service.BluetoothUnpairError):
        await bluetooth_service._unpair_all_devices(timeout_sec=0)


@pytest.mark.asyncio
async def test_pairing_mode_requires_pairable_and_discoverable(mocker):
    mocker.patch.object(
        bluetooth_service,
        "run_command_async",
        new=AsyncMock(
            return_value=MagicMock(
                stdout="Controller AA:BB:CC:DD:EE:FF wlanpi\n"
                "\tPairable: yes\n"
                "\tDiscoverable: yes\n"
            )
        ),
    )

    assert await bluetooth_service._pairing_mode_active() is True


@pytest.mark.asyncio
async def test_bluetooth_pair_rejects_concurrent_request():
    assert bluetooth_service._pairing_lock.acquire(blocking=False)
    try:
        with pytest.raises(bluetooth_service.BluetoothPairingInProgressError):
            await bluetooth_service.bluetooth_pair()
    finally:
        bluetooth_service._pairing_lock.release()


@pytest.mark.asyncio
async def test_bluetooth_pair_rejects_active_pairing_window(mocker):
    mocker.patch.object(
        bluetooth_service, "_bluetooth_present_async", new=AsyncMock(return_value=True)
    )
    mocker.patch.object(bluetooth_service, "_ensure_bluetooth_powered", new=AsyncMock())
    mocker.patch.object(
        bluetooth_service, "_pairing_mode_active", new=AsyncMock(return_value=True)
    )
    unpair = mocker.patch.object(
        bluetooth_service, "_unpair_all_devices", new=AsyncMock()
    )

    with pytest.raises(bluetooth_service.BluetoothPairingInProgressError):
        await bluetooth_service.bluetooth_pair()

    unpair.assert_not_awaited()


@pytest.mark.asyncio
async def test_bluetooth_pair_cancellation_releases_lock(mocker):
    started = asyncio.Event()

    async def wait_for_cancellation():
        started.set()
        await asyncio.Event().wait()

    mocker.patch.object(
        bluetooth_service,
        "_bluetooth_present_async",
        side_effect=wait_for_cancellation,
    )

    task = asyncio.create_task(bluetooth_service.bluetooth_pair())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert bluetooth_service._pairing_lock.acquire(blocking=False)
    bluetooth_service._pairing_lock.release()
