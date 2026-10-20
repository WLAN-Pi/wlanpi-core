"""Bluetooth adapter status, power, and pairing helpers."""

import asyncio
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command, run_command_async

log = get_logger(__name__)

BLUETOOTH_COMMAND_TIMEOUT_SEC = 5
BLUETOOTH_UNPAIR_TIMEOUT_SEC = 30
BLUETOOTH_PAIRING_START_TIMEOUT_SEC = 10
BLUETOOTH_STATE_FILE = "/etc/wlanpi-bluetooth/state"
BLUETOOTH_POWER_ON_TIMEOUT_SEC = 10
BLUETOOTH_ADAPTER_COMMAND = "/usr/bin/wlanpi-bt-adapter"
BLUETOOTH_ADAPTER_TIMEOUT_SEC = 2

_pairing_lock = threading.Lock()
# Not bluetoothctl (default controller only), bt-device -l (lists unpaired) or
# GetManagedObjects (busctl --json fails on ManufacturerData a{qv}).
# BlueZ drops scanned devices at any time, so an unreadable path that vanished is skipped.
_BLUEZ_TREE_CMD = ["busctl", "--system", "tree", "--list", "org.bluez"]


def _bluez_device_paths(tree: str, adapter: str) -> list[str]:
    # No adapter object means BlueZ is restarting and can't list pairings.
    if f"/org/bluez/{adapter}" not in tree.split():
        raise RunCommandError(f"BlueZ has not registered {adapter}", 1)
    return re.findall(rf"^/org/bluez/{adapter}/dev_[0-9A-F_]+$", tree, re.MULTILINE)


def _bluez_device_cmd(path: str) -> list[str]:
    return [
        "busctl",
        "--system",
        "--json=short",
        "get-property",
        "org.bluez",
        path,
        "org.bluez.Device1",
        "Paired",
        "Address",
        "Alias",
    ]


def _parse_paired_device(output: str) -> tuple[str, str] | None:
    """(MAC, alias) from a device's Paired, Address and Alias, or None if unpaired."""
    paired, address, alias = (json.loads(line)["data"] for line in output.splitlines())
    return (address.upper(), alias) if paired else None


class BluetoothPairingError(RuntimeError):
    """Base error for failures while entering Bluetooth pairing mode."""


class BluetoothPairingInProgressError(BluetoothPairingError):
    """Raised when another pairing request already owns the adapter."""


class BluetoothUnpairError(BluetoothPairingError):
    """Raised when existing pairings cannot be removed before the deadline."""


def _grep_text(result: Any, pattern: str) -> str:
    """First non-empty line of a grep result as text."""
    filtered = result.grep_stdout_for_string(pattern)
    if isinstance(filtered, list):
        return filtered[0].strip() if filtered else ""
    return filtered.strip()


def bluetooth_adapter() -> str | None:
    """Return the adapter wlanpi-bluetooth uses, such as ``hci1``, or None.

    hci0 can be a USB dongle (probe order), so it is the fallback only when an
    older wlanpi-bluetooth lacks ``wlanpi-bt-adapter``, never when it fails.
    """
    try:
        result = run_command(
            [BLUETOOTH_ADAPTER_COMMAND],
            raise_on_fail=False,
            timeout=BLUETOOTH_ADAPTER_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return "hci0"
    except (OSError, subprocess.TimeoutExpired):
        return None
    adapter = result.stdout.strip()
    if result.success and re.fullmatch(r"hci\d+", adapter):
        return adapter
    return None


def bluetooth_present(adapter: str) -> bool:
    """Return whether hciconfig lists `adapter` (it works with no devices present)."""
    cmd = "hciconfig"
    return bool(_grep_text(run_command(cmd=cmd, raise_on_fail=True), adapter))


def bluetooth_name(adapter: str) -> str:
    """Return the adapter name."""
    cmd = f"bt-adapter -a {adapter} -i"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string(
        "Name", split=True
    )
    return filtered[0].strip().split(" ")[1] if filtered else ""


def bluetooth_alias(adapter: str) -> str:
    """Return the adapter alias."""
    cmd = f"bt-adapter -a {adapter} -i"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string(
        "Alias", split=True
    )
    return filtered[0].strip().split(" ")[1] if filtered else ""


def bluetooth_address(adapter: str) -> str:
    """Return the adapter MAC address."""
    cmd = f"bt-adapter -a {adapter} -i"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string(
        "Address", split=True
    )
    return filtered[0].strip().split(" ")[1] if filtered else ""


def bluetooth_power(adapter: str) -> str:
    """Return the adapter's hciconfig UP line, or "" when it is down."""
    cmd = f"hciconfig {adapter}"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_pattern(
        r"^\s+UP", split=True
    )
    return filtered[0].strip() if filtered else ""


def _bluetooth_rfkill_blocked() -> bool:
    """Return True if any bluetooth rfkill switch is soft- or hard-blocked."""
    for entry in Path("/sys/class/rfkill").glob("rfkill*"):
        try:
            if (entry / "type").read_text().strip() != "bluetooth":
                continue
            if (entry / "soft").read_text().strip() == "1":
                return True
            if (entry / "hard").read_text().strip() == "1":
                return True
        except OSError:
            continue
    return False


def bluetooth_set_power(power: bool, adapter: str) -> bool:
    """Set the adapter power state and persist it."""
    if power:
        if bluetooth_power(adapter):
            return True
        # The USB BT adapter ships rfkill soft-blocked; unblock before powering on.
        run_command(["rfkill", "unblock", "bluetooth"], raise_on_fail=False)
        deadline = time.monotonic() + BLUETOOTH_POWER_ON_TIMEOUT_SEC
        while time.monotonic() < deadline:
            try:
                run_command(
                    f"bt-adapter -a {adapter} --set Powered 1",
                    raise_on_fail=True,
                )
            except RunCommandError:
                pass  # org.bluez.Error.Busy while the adapter is enabling
            if bluetooth_power(adapter):
                break
            time.sleep(0.5)
        if not bluetooth_power(adapter):
            return False
        bt_state = 1
    else:
        if not bluetooth_power(adapter):
            return True
        run_command(
            f"bt-adapter -a {adapter} --set Powered 0",
            raise_on_fail=True,
        )
        bt_state = 0

    with open(BLUETOOTH_STATE_FILE, "w") as bt_state_file:
        bt_state_file.write(str(bt_state))
    return True


def bluetooth_paired_devices(adapter: str) -> dict[str, str] | None:
    """Return a dictionary of paired devices, indexed by MAC address."""
    if not bluetooth_present(adapter):
        return None

    tree = run_command(cmd=_BLUEZ_TREE_CMD, raise_on_fail=True).stdout
    paired = {}
    for path in _bluez_device_paths(tree, adapter):
        try:
            result = run_command(cmd=_bluez_device_cmd(path), raise_on_fail=True)
        except RunCommandError:
            now = run_command(cmd=_BLUEZ_TREE_CMD, raise_on_fail=True).stdout
            if path in _bluez_device_paths(now, adapter):
                raise
            continue
        if device := _parse_paired_device(result.stdout):
            paired[device[0]] = device[1]
    return paired or None


def bluetooth_status() -> Any:
    """Return the current bluetooth status, or False when absent."""
    status: dict[str, Any] = {}
    adapter = bluetooth_adapter()

    if adapter is None or not bluetooth_present(adapter):
        return False

    status["name"] = bluetooth_name(adapter)
    status["alias"] = bluetooth_alias(adapter)
    status["addr"] = bluetooth_address(adapter)
    status["paired_devices"] = []

    if bluetooth_power(adapter):
        status["power"] = "On"
    else:
        status["power"] = "Off"

    paired_devices = bluetooth_paired_devices(adapter)

    if paired_devices:
        for mac in paired_devices:
            status["paired_devices"].append({"name": paired_devices[mac], "addr": mac})

    status["blocked"] = _bluetooth_rfkill_blocked()

    return status


def _parse_adapter_property(output: str, property_name: str) -> str:
    for line in output.splitlines():
        key, separator, value = line.strip().partition(":")
        if separator and key.casefold() == property_name.casefold():
            return value.strip()
    return ""


async def _bluetooth_present_async(adapter: str) -> bool:
    result = await run_command_async(
        ["hciconfig"],
        raise_on_fail=True,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    return bool(_grep_text(result, adapter))


async def _bluetooth_powered_async(adapter: str) -> bool:
    result = await run_command_async(
        ["hciconfig", adapter],
        raise_on_fail=True,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    return bool(result.grep_stdout_for_pattern(r"^\s+UP", split=True))


async def _ensure_bluetooth_powered(adapter: str) -> None:
    if await _bluetooth_powered_async(adapter):
        return

    await run_command_async(
        ["rfkill", "unblock", "bluetooth"],
        raise_on_fail=False,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    deadline = time.monotonic() + BLUETOOTH_POWER_ON_TIMEOUT_SEC
    while time.monotonic() < deadline:
        try:
            await run_command_async(
                ["bt-adapter", "-a", adapter, "--set", "Powered", "1"],
                raise_on_fail=True,
                timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
            )
        except RunCommandError:
            pass  # org.bluez.Error.Busy while the adapter is enabling
        if await _bluetooth_powered_async(adapter):
            break
        await asyncio.sleep(0.5)
    if not await _bluetooth_powered_async(adapter):
        raise BluetoothPairingError("Bluetooth did not power on")
    with open(BLUETOOTH_STATE_FILE, "w") as bt_state_file:
        bt_state_file.write("1")


async def _bluetooth_alias_async(adapter: str) -> str:
    result = await run_command_async(
        ["bt-adapter", "-a", adapter, "-i"],
        raise_on_fail=True,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    alias = _parse_adapter_property(result.stdout, "Alias")
    if not alias:
        raise BluetoothPairingError("Unable to determine the Bluetooth alias")
    return alias


async def _bluetooth_paired_devices_async(
    adapter: str,
    timeout_sec: float = BLUETOOTH_COMMAND_TIMEOUT_SEC,
) -> dict[str, str]:
    tree = await run_command_async(
        _BLUEZ_TREE_CMD,
        raise_on_fail=True,
        timeout=timeout_sec,
    )
    paired = {}
    for path in _bluez_device_paths(tree.stdout, adapter):
        try:
            result = await run_command_async(
                _bluez_device_cmd(path),
                raise_on_fail=True,
                timeout=timeout_sec,
            )
        except RunCommandError:
            now = await run_command_async(
                _BLUEZ_TREE_CMD,
                raise_on_fail=True,
                timeout=timeout_sec,
            )
            if path in _bluez_device_paths(now.stdout, adapter):
                raise
            continue
        if device := _parse_paired_device(result.stdout):
            paired[device[0]] = device[1]
    return paired


async def _unpair_all_devices(
    adapter: str,
    timeout_sec: float = BLUETOOTH_UNPAIR_TIMEOUT_SEC,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            paired = await _bluetooth_paired_devices_async(
                adapter, timeout_sec=min(BLUETOOTH_COMMAND_TIMEOUT_SEC, remaining)
            )
        except TimeoutError:
            paired = None
            log.warning("Timed out while checking for paired Bluetooth devices")

        if paired == {}:
            return

        for mac in paired or {}:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                result = await run_command_async(
                    ["bt-device", "-a", adapter, "-r", mac],
                    raise_on_fail=False,
                    timeout=min(BLUETOOTH_COMMAND_TIMEOUT_SEC, remaining),
                )
                if not result.success:
                    log.warning("Failed to remove paired Bluetooth device %s", mac)
            except TimeoutError:
                log.warning("Timed out removing paired Bluetooth device %s", mac)

        remaining = deadline - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(min(1, remaining))

    raise BluetoothUnpairError(
        "Unable to remove the existing Bluetooth pairing before the deadline"
    )


async def _pairing_mode_active(adapter: str) -> bool:
    result = await run_command_async(
        ["bt-adapter", "-a", adapter, "-i"],
        raise_on_fail=True,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    # bt-adapter prints writable flags as "Pairable: 1 [rw]".
    return all(
        _parse_adapter_property(result.stdout, flag).partition(" ")[0] == "1"
        for flag in ("Pairable", "Discoverable")
    )


async def bluetooth_pair() -> dict[str, Any]:
    """Enter discoverable pairing mode via ``bt-timedpair``, unpairing existing devices first as FPMS does."""
    if not _pairing_lock.acquire(blocking=False):
        raise BluetoothPairingInProgressError(
            "Bluetooth pairing is already in progress"
        )

    try:
        adapter = await asyncio.to_thread(bluetooth_adapter)
        if adapter is None or not await _bluetooth_present_async(adapter):
            raise ValueError("Bluetooth hardware not found")

        await _ensure_bluetooth_powered(adapter)
        if await _pairing_mode_active(adapter):
            raise BluetoothPairingInProgressError(
                "Bluetooth pairing is already in progress"
            )
        alias = await _bluetooth_alias_async(adapter)
        await _unpair_all_devices(adapter)

        await run_command_async(
            ["systemctl", "start", "bt-timedpair.service"],
            raise_on_fail=True,
            timeout=BLUETOOTH_PAIRING_START_TIMEOUT_SEC,
        )
        if not await _pairing_mode_active(adapter):
            raise BluetoothPairingError(
                "Bluetooth did not enter discoverable pairing mode"
            )

        return {
            "status": "discoverable",
            "alias": alias,
            "message": f'Bluetooth is on. Discoverable as "{alias}"',
        }
    except BluetoothPairingError:
        raise
    except TimeoutError as exc:
        raise BluetoothPairingError("A Bluetooth command timed out") from exc
    except RunCommandError as exc:
        raise BluetoothPairingError("A Bluetooth command failed") from exc
    finally:
        _pairing_lock.release()
