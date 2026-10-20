"""Unit tests for blinker and bluetooth pair services."""

import asyncio
import json
import signal
import subprocess
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
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
    mocker.patch.object(utils_service, "_blinker_script_pids", return_value=[1234])
    kill = mocker.patch.object(utils_service.os, "kill")

    assert utils_service.stop_port_blinker() == {
        "active": False,
        "status": "stopped",
    }

    kill.assert_called_once_with(1234, signal.SIGTERM)
    assert running.call_count == 2


# BlueZ's device objects: (Paired, Address, Alias). hci1 is the chosen adapter.
BLUEZ_DEVICES = {
    "/org/bluez/hci0/dev_11_22_33_44_55_66": (True, "11:22:33:44:55:66", "Dongle Peer"),
    "/org/bluez/hci1/dev_AA_BB_CC_DD_EE_FF": (True, "aa:bb:cc:dd:ee:ff", "Test Phone"),
    "/org/bluez/hci1/dev_AA_BB_CC_DD_EE_00": (False, "AA:BB:CC:DD:EE:00", "Nearby"),
}


def _bluez(dropped=(), unreadable=(), relist=None):
    """
    Fake busctl as run_command returns it, for BLUEZ_DEVICES.

    ``dropped`` paths are listed once and then gone; ``unreadable`` ones stay
    listed but can't be read. ``relist`` replaces every listing after the
    first: an exception to raise, or the paths to list.
    """
    listings = []

    def busctl(cmd, **_kwargs):
        if cmd == ["busctl", "--system", "tree", "--list", "org.bluez"]:
            paths = ["/", "/org", "/org/bluez", "/org/bluez/hci0", "/org/bluez/hci1"]
            paths += [
                *BLUEZ_DEVICES,
                "/org/bluez/hci1/dev_AA_BB_CC_DD_EE_FF/service0001",
            ]
            paths += [*unreadable, *([] if listings else dropped)]
            if listings and isinstance(relist, Exception):
                raise relist
            if listings and relist is not None:
                paths = relist
            listings.append(cmd)
            return CommandResult("\n".join(paths) + "\n", "", 0)
        prefix, suffix = (
            ["busctl", "--system", "--json=short", "get-property"],
            [
                "org.bluez.Device1",
                "Paired",
                "Address",
                "Alias",
            ],
        )
        assert cmd[:4] == prefix and cmd[4] == "org.bluez" and cmd[6:] == suffix
        if cmd[5] not in BLUEZ_DEVICES:
            raise RunCommandError("Unknown object", 1)
        values = zip(("b", "s", "s"), BLUEZ_DEVICES[cmd[5]], strict=True)
        lines = [json.dumps({"type": t, "data": v}) for t, v in values]
        return CommandResult("\n".join(lines) + "\n", "", 0)

    busctl.listings = listings
    return busctl


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (CommandResult("hci1\n", "", 0), "hci1"),
        (FileNotFoundError("wlanpi-bt-adapter"), "hci0"),
        (CommandResult("", "", 1), None),
        (CommandResult("\n", "", 0), None),
        (CommandResult("not-an-adapter\n", "", 0), None),
        (PermissionError("wlanpi-bt-adapter"), None),
        (subprocess.TimeoutExpired("wlanpi-bt-adapter", 2), None),
    ],
)
def test_bluetooth_adapter_falls_back_to_hci0_only_without_the_selector(
    mocker, result, expected
):
    run_command = mocker.patch.object(
        bluetooth_service, "run_command", side_effect=[result]
    )

    assert bluetooth_service.bluetooth_adapter() == expected
    run_command.assert_called_once_with(
        ["/usr/bin/wlanpi-bt-adapter"], raise_on_fail=False, timeout=2
    )


def test_bluetooth_paired_devices_lists_only_the_adapters_paired_devices(mocker):
    present = mocker.patch.object(
        bluetooth_service, "bluetooth_present", return_value=True
    )
    run_command = mocker.patch.object(
        bluetooth_service,
        "run_command",
        side_effect=_bluez(),
    )

    assert bluetooth_service.bluetooth_paired_devices("hci1") == {
        "AA:BB:CC:DD:EE:FF": "Test Phone"
    }
    present.assert_any_call("hci1")
    assert [c.kwargs["cmd"] for c in run_command.call_args_list] == [
        ["busctl", "--system", "tree", "--list", "org.bluez"],
        bluetooth_service._bluez_device_cmd("/org/bluez/hci1/dev_AA_BB_CC_DD_EE_FF"),
        bluetooth_service._bluez_device_cmd("/org/bluez/hci1/dev_AA_BB_CC_DD_EE_00"),
    ]
    assert bluetooth_service._bluez_device_cmd("/x")[2:4] == [
        "--json=short",
        "get-property",
    ]
    assert bluetooth_service.bluetooth_paired_devices("hci0") == {
        "11:22:33:44:55:66": "Dongle Peer"
    }


def test_bluetooth_paired_devices_skips_a_device_dropped_since_the_listing(mocker):
    mocker.patch.object(bluetooth_service, "bluetooth_present", return_value=True)
    busctl = _bluez(dropped=["/org/bluez/hci1/dev_AA_BB_CC_DD_EE_09"])
    mocker.patch.object(bluetooth_service, "run_command", side_effect=busctl)

    assert bluetooth_service.bluetooth_paired_devices("hci1") == {
        "AA:BB:CC:DD:EE:FF": "Test Phone"
    }
    assert len(busctl.listings) == 2


def test_bluetooth_paired_devices_raises_if_a_listed_device_cannot_be_read(mocker):
    mocker.patch.object(bluetooth_service, "bluetooth_present", return_value=True)
    mocker.patch.object(
        bluetooth_service,
        "run_command",
        side_effect=_bluez(unreadable=["/org/bluez/hci1/dev_AA_BB_CC_DD_EE_09"]),
    )

    with pytest.raises(RunCommandError):
        bluetooth_service.bluetooth_paired_devices("hci1")


@pytest.mark.parametrize(
    "relist",
    [RunCommandError("busctl failed", 1), ["/", "/org", "/org/bluez"]],
    ids=["relist-fails", "adapter-gone"],
)
def test_bluetooth_paired_devices_raises_if_a_read_failure_cannot_be_explained(
    mocker, relist
):
    mocker.patch.object(bluetooth_service, "bluetooth_present", return_value=True)
    mocker.patch.object(
        bluetooth_service,
        "run_command",
        side_effect=_bluez(
            dropped=["/org/bluez/hci1/dev_AA_BB_CC_DD_EE_09"], relist=relist
        ),
    )

    with pytest.raises(RunCommandError):
        bluetooth_service.bluetooth_paired_devices("hci1")


def test_bluetooth_paired_devices_raises_if_bluez_has_not_registered_the_adapter(
    mocker,
):
    mocker.patch.object(bluetooth_service, "bluetooth_present", return_value=True)
    mocker.patch.object(bluetooth_service, "run_command", side_effect=_bluez())

    with pytest.raises(RunCommandError):
        bluetooth_service.bluetooth_paired_devices("hci2")


def test_bluetooth_status_and_pair_treat_a_failed_selector_as_no_adapter(mocker):
    mocker.patch.object(bluetooth_service, "bluetooth_adapter", return_value=None)
    present = mocker.patch.object(bluetooth_service, "bluetooth_present")
    present_async = mocker.patch.object(
        bluetooth_service, "_bluetooth_present_async", new=AsyncMock()
    )
    run_command = mocker.patch.object(
        bluetooth_service, "run_command_async", new=AsyncMock()
    )

    assert bluetooth_service.bluetooth_status() is False
    with pytest.raises(ValueError):
        asyncio.run(bluetooth_service.bluetooth_pair())
    present.assert_not_called()
    present_async.assert_not_awaited()
    run_command.assert_not_awaited()


def test_bluetooth_paired_devices_none_when_nothing_paired(mocker):
    mocker.patch.object(bluetooth_service, "bluetooth_present", return_value=True)
    devices = {p: d for p, d in BLUEZ_DEVICES.items() if not d[0]}
    mocker.patch.dict(BLUEZ_DEVICES, devices, clear=True)
    mocker.patch.object(bluetooth_service, "run_command", side_effect=_bluez())

    assert bluetooth_service.bluetooth_paired_devices("hci1") is None


def test_bluetooth_status_uses_one_adapter(mocker):
    mocker.patch.object(bluetooth_service, "bluetooth_adapter", return_value="hci1")
    helpers = {
        name: mocker.patch.object(bluetooth_service, name, return_value=value)
        for name, value in [
            ("bluetooth_present", True),
            ("bluetooth_name", "wlanpi"),
            ("bluetooth_alias", "wlanpi-bc2"),
            ("bluetooth_address", "AA:BB:CC:00:11:22"),
            ("bluetooth_power", "UP RUNNING"),
            ("bluetooth_paired_devices", {"AA:BB:CC:DD:EE:FF": "Test Phone"}),
        ]
    }
    mocker.patch.object(
        bluetooth_service, "_bluetooth_rfkill_blocked", return_value=False
    )

    assert bluetooth_service.bluetooth_status() == {
        "name": "wlanpi",
        "alias": "wlanpi-bc2",
        "addr": "AA:BB:CC:00:11:22",
        "paired_devices": [{"name": "Test Phone", "addr": "AA:BB:CC:DD:EE:FF"}],
        "power": "On",
        "blocked": False,
    }
    for helper in helpers.values():
        helper.assert_called_once_with("hci1")


@pytest.mark.asyncio
async def test_bluetooth_pair_discoverable(mocker):
    mocker.patch.object(bluetooth_service, "bluetooth_adapter", return_value="hci1")
    present = mocker.patch.object(
        bluetooth_service, "_bluetooth_present_async", new=AsyncMock(return_value=True)
    )
    powered = mocker.patch.object(
        bluetooth_service, "_ensure_bluetooth_powered", new=AsyncMock()
    )
    alias = mocker.patch.object(
        bluetooth_service,
        "_bluetooth_alias_async",
        new=AsyncMock(return_value="wlanpi-test"),
    )
    unpair = mocker.patch.object(
        bluetooth_service, "_unpair_all_devices", new=AsyncMock()
    )
    pairing = mocker.patch.object(
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
    for helper in (present, powered, alias, unpair):
        helper.assert_awaited_once_with("hci1")
    assert pairing.await_args_list == [call("hci1"), call("hci1")]


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

    await bluetooth_service._unpair_all_devices("hci1", timeout_sec=30)

    run_command.assert_awaited_once()
    assert run_command.await_args.args[0] == [
        "bt-device",
        "-a",
        "hci1",
        "-r",
        "AA:BB:CC:DD:EE:FF",
    ]
    assert paired_devices.await_count == 2
    assert all(c.args[0] == "hci1" for c in paired_devices.await_args_list)


@pytest.mark.asyncio
async def test_paired_devices_async_filters_by_adapter(mocker):
    run_command = mocker.patch.object(
        bluetooth_service,
        "run_command_async",
        new=AsyncMock(side_effect=_bluez()),
    )

    assert await bluetooth_service._bluetooth_paired_devices_async(
        "hci1", timeout_sec=3
    ) == {"AA:BB:CC:DD:EE:FF": "Test Phone"}
    assert [c.kwargs["timeout"] for c in run_command.await_args_list] == [3, 3, 3]


@pytest.mark.asyncio
async def test_paired_devices_async_skips_only_dropped_devices(mocker):
    dropped = _bluez(dropped=["/org/bluez/hci1/dev_AA_BB_CC_DD_EE_09"])
    mocker.patch.object(
        bluetooth_service, "run_command_async", new=AsyncMock(side_effect=dropped)
    )
    assert await bluetooth_service._bluetooth_paired_devices_async("hci1") == {
        "AA:BB:CC:DD:EE:FF": "Test Phone"
    }

    for busctl in (
        _bluez(unreadable=["/org/bluez/hci1/dev_AA_BB_CC_DD_EE_09"]),
        _bluez(
            dropped=["/org/bluez/hci1/dev_AA_BB_CC_DD_EE_09"],
            relist=RunCommandError("busctl failed", 1),
        ),
        _bluez(
            dropped=["/org/bluez/hci1/dev_AA_BB_CC_DD_EE_09"],
            relist=["/", "/org", "/org/bluez"],
        ),
    ):
        mocker.patch.object(
            bluetooth_service, "run_command_async", new=AsyncMock(side_effect=busctl)
        )
        with pytest.raises(RunCommandError):
            await bluetooth_service._bluetooth_paired_devices_async("hci1")


@pytest.mark.asyncio
async def test_paired_devices_async_raises_when_bluez_cannot_be_read(mocker):
    mocker.patch.object(
        bluetooth_service,
        "run_command_async",
        new=AsyncMock(side_effect=RunCommandError("busctl failed", 1)),
    )

    with pytest.raises(RunCommandError):
        await bluetooth_service._bluetooth_paired_devices_async("hci1")


@pytest.mark.asyncio
async def test_unpair_all_devices_raises_at_deadline():
    with pytest.raises(bluetooth_service.BluetoothUnpairError):
        await bluetooth_service._unpair_all_devices("hci0", timeout_sec=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pairable", "discoverable", "expected"),
    [(1, 1, True), (1, 0, False), (0, 1, False)],
)
async def test_pairing_mode_requires_pairable_and_discoverable(
    mocker, pairable, discoverable, expected
):
    run_command = mocker.patch.object(
        bluetooth_service,
        "run_command_async",
        new=AsyncMock(
            return_value=CommandResult(
                "[hci1]\n"
                "  Name: wlanpi\n"
                "  Address: AA:BB:CC:DD:EE:FF\n"
                "  Alias: wlanpi-bc2 [rw]\n"
                f"  Discoverable: {discoverable} [rw]\n"
                "  DiscoverableTimeout: 30 [rw]\n"
                f"  Pairable: {pairable} [rw]\n"
                "  PairableTimeout: 30 [rw]\n"
                "  Powered: 1 [rw]\n",
                "",
                0,
            )
        ),
    )

    assert await bluetooth_service._pairing_mode_active("hci1") is expected
    assert run_command.await_args.args[0] == ["bt-adapter", "-a", "hci1", "-i"]


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
    mocker.patch.object(bluetooth_service, "bluetooth_adapter", return_value="hci0")
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

    async def wait_for_cancellation(_adapter):
        started.set()
        await asyncio.Event().wait()

    mocker.patch.object(bluetooth_service, "bluetooth_adapter", return_value="hci0")
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


def test_bluetooth_set_power_unblocks_rfkill_and_retries_busy(mocker, tmp_path):
    mocker.patch.object(
        bluetooth_service, "BLUETOOTH_STATE_FILE", str(tmp_path / "state")
    )
    power = mocker.patch.object(
        bluetooth_service, "bluetooth_power", side_effect=["", "", "UP", "UP"]
    )
    run_command = mocker.patch.object(
        bluetooth_service,
        "run_command",
        side_effect=[MagicMock(), RunCommandError("Busy", 1), MagicMock()],
    )
    mocker.patch.object(bluetooth_service.time, "sleep")

    assert bluetooth_service.bluetooth_set_power(True, "hci1") is True

    assert run_command.call_args_list[0].args[0] == ["rfkill", "unblock", "bluetooth"]
    assert run_command.call_count == 3
    assert run_command.call_args.args[0] == "bt-adapter -a hci1 --set Powered 1"
    assert power.call_count >= 2
    power.assert_called_with("hci1")


@pytest.mark.asyncio
async def test_ensure_bluetooth_powered_unblocks_rfkill(mocker, tmp_path):
    mocker.patch.object(
        bluetooth_service, "BLUETOOTH_STATE_FILE", str(tmp_path / "state")
    )
    mocker.patch.object(
        bluetooth_service,
        "_bluetooth_powered_async",
        new=AsyncMock(side_effect=[False, True, True]),
    )
    run_command = mocker.patch.object(
        bluetooth_service,
        "run_command_async",
        new=AsyncMock(return_value=MagicMock(success=True)),
    )

    await bluetooth_service._ensure_bluetooth_powered("hci0")

    assert run_command.await_args_list[0].args[0] == ["rfkill", "unblock", "bluetooth"]


@pytest.mark.asyncio
async def test_bluetooth_powered_async_matches_up_line(mocker):
    mocker.patch.object(
        bluetooth_service,
        "run_command_async",
        new=AsyncMock(
            return_value=CommandResult(
                "hci0:\tType: Primary  Bus: USB\n\tUP RUNNING\n", "", 0
            )
        ),
    )

    assert await bluetooth_service._bluetooth_powered_async("hci0") is True


@pytest.mark.asyncio
async def test_bluetooth_powered_async_false_when_down(mocker):
    mocker.patch.object(
        bluetooth_service,
        "run_command_async",
        new=AsyncMock(
            return_value=CommandResult(
                "hci0:\tType: Primary  Bus: USB\n\tDOWN\n", "", 0
            )
        ),
    )

    assert await bluetooth_service._bluetooth_powered_async("hci0") is False
