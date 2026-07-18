import asyncio
import re
import threading
import time

from wlanpi_core.constants import BT_ADAPTER
from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command, run_command_async

log = get_logger(__name__)

BLUETOOTH_COMMAND_TIMEOUT_SEC = 5
BLUETOOTH_UNPAIR_TIMEOUT_SEC = 30
BLUETOOTH_PAIRING_START_TIMEOUT_SEC = 10
BLUETOOTH_STATE_FILE = "/etc/wlanpi-bluetooth/state"

_pairing_lock = threading.Lock()
_PAIRED_DEVICE_RE = re.compile(
    r"^Device\s+((?:[0-9A-F]{2}:){5}[0-9A-F]{2})\s+(.+)$", re.IGNORECASE
)


class BluetoothPairingError(RuntimeError):
    """Base error for failures while entering Bluetooth pairing mode."""


class BluetoothPairingInProgressError(BluetoothPairingError):
    """Raised when another pairing request already owns the adapter."""


class BluetoothUnpairError(BluetoothPairingError):
    """Raised when existing pairings cannot be removed before the deadline."""


def bluetooth_present():
    """
    We want to use hciconfig here as it works OK when no devices are present
    """
    cmd = f"hciconfig"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string(
        BT_ADAPTER,
    )
    return filtered.strip() if filtered else ""


def bluetooth_name():
    cmd = f"bt-adapter -a {BT_ADAPTER} -i"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string(
        "Name", split=True
    )
    return filtered[0].strip().split(" ")[1] if filtered else ""


def bluetooth_alias():
    cmd = f"bt-adapter -a {BT_ADAPTER} -i"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string(
        "Alias", split=True
    )
    return filtered[0].strip().split(" ")[1] if filtered else ""


def bluetooth_address():
    cmd = f"bt-adapter -a {BT_ADAPTER} -i"
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_string(
        "Address", split=True
    )
    return filtered[0].strip().split(" ")[1] if filtered else ""


def bluetooth_power():
    """
    We want to use hciconfig here as it works OK when no devices are present
    """
    cmd = f"hciconfig {BT_ADAPTER} "
    filtered = run_command(cmd=cmd, raise_on_fail=True).grep_stdout_for_pattern(
        r"^\s+UP", split=True
    )
    return filtered[0].strip() if filtered else ""


def bluetooth_set_power(power):
    bluetooth_is_on = bluetooth_power()

    if power:
        if bluetooth_is_on:
            return True
        cmd = f"bt-adapter -a {BT_ADAPTER} --set Powered 1"
        bt_state = 1
    else:
        if not bluetooth_is_on:
            return True
        cmd = f"bt-adapter -a {BT_ADAPTER} --set Powered 0"
        bt_state = 0
    result = run_command(cmd, shell=True, raise_on_fail=True).stdout
    with open("/etc/wlanpi-bluetooth/state", "w") as bt_state_file:
        bt_state_file.write(str(bt_state))

    if result:
        return True
    else:
        return False


def bluetooth_paired_devices():
    """
    Returns a dictionary of paired devices, indexed by MAC address
    """
    if not bluetooth_present():
        return None

    result = run_command(cmd=["bluetoothctl", "devices", "Paired"], raise_on_fail=True)
    paired = _parse_paired_devices(result.stdout)
    return paired or None


def bluetooth_status():
    status = {}

    if not bluetooth_present():
        return False

    status["name"] = bluetooth_name()
    status["alias"] = bluetooth_alias()
    status["addr"] = bluetooth_address()
    status["paired_devices"] = []

    if bluetooth_power():
        status["power"] = "On"
    else:
        status["power"] = "Off"

    paired_devices = bluetooth_paired_devices()

    if paired_devices:
        for mac in paired_devices:
            status["paired_devices"].append({"name": paired_devices[mac], "addr": mac})

    return status


def _parse_paired_devices(output: str) -> dict[str, str]:
    paired = {}
    for line in output.splitlines():
        match = _PAIRED_DEVICE_RE.match(line.strip())
        if match:
            mac, name = match.groups()
            paired[mac.upper()] = name
    return paired


def _parse_adapter_property(output: str, property_name: str) -> str:
    for line in output.splitlines():
        key, separator, value = line.strip().partition(":")
        if separator and key.casefold() == property_name.casefold():
            return value.strip()
    return ""


async def _bluetooth_present_async() -> bool:
    result = await run_command_async(
        ["hciconfig"],
        raise_on_fail=True,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    return bool(result.grep_stdout_for_string(BT_ADAPTER).strip())


async def _bluetooth_powered_async() -> bool:
    result = await run_command_async(
        ["hciconfig", BT_ADAPTER],
        raise_on_fail=True,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    return bool(result.grep_stdout_for_pattern(r"^\s+UP", split=False).strip())


async def _ensure_bluetooth_powered() -> None:
    if await _bluetooth_powered_async():
        return

    await run_command_async(
        ["bt-adapter", "-a", BT_ADAPTER, "--set", "Powered", "1"],
        raise_on_fail=True,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    with open(BLUETOOTH_STATE_FILE, "w") as bt_state_file:
        bt_state_file.write("1")


async def _bluetooth_alias_async() -> str:
    result = await run_command_async(
        ["bt-adapter", "-a", BT_ADAPTER, "-i"],
        raise_on_fail=True,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    alias = _parse_adapter_property(result.stdout, "Alias")
    if not alias:
        raise BluetoothPairingError("Unable to determine the Bluetooth alias")
    return alias


async def _bluetooth_paired_devices_async(
    timeout_sec: float = BLUETOOTH_COMMAND_TIMEOUT_SEC,
) -> dict[str, str]:
    result = await run_command_async(
        ["bluetoothctl", "devices", "Paired"],
        raise_on_fail=True,
        timeout=timeout_sec,
    )
    return _parse_paired_devices(result.stdout)


async def _unpair_all_devices(
    timeout_sec: float = BLUETOOTH_UNPAIR_TIMEOUT_SEC,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            paired = await _bluetooth_paired_devices_async(
                timeout_sec=min(BLUETOOTH_COMMAND_TIMEOUT_SEC, remaining)
            )
        except asyncio.TimeoutError:
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
                    ["bluetoothctl", "remove", mac],
                    raise_on_fail=False,
                    timeout=min(BLUETOOTH_COMMAND_TIMEOUT_SEC, remaining),
                )
                if not result.success:
                    log.warning("Failed to remove paired Bluetooth device %s", mac)
            except asyncio.TimeoutError:
                log.warning("Timed out removing paired Bluetooth device %s", mac)

        remaining = deadline - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(min(1, remaining))

    raise BluetoothUnpairError(
        "Unable to remove the existing Bluetooth pairing before the deadline"
    )


async def _pairing_mode_active() -> bool:
    result = await run_command_async(
        ["bluetoothctl", "show"],
        raise_on_fail=True,
        timeout=BLUETOOTH_COMMAND_TIMEOUT_SEC,
    )
    properties = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.strip().partition(":")
        if separator:
            properties[key.casefold()] = value.strip().casefold()
    return (
        properties.get("pairable") == "yes" and properties.get("discoverable") == "yes"
    )


async def bluetooth_pair():
    """
    Enter discoverable pairing mode via ``bt-timedpair``.

    Unpairs existing devices first (fpms parity) then starts timed pairing.
    """
    if not _pairing_lock.acquire(blocking=False):
        raise BluetoothPairingInProgressError(
            "Bluetooth pairing is already in progress"
        )

    try:
        if not await _bluetooth_present_async():
            raise ValueError("Bluetooth hardware not found")

        await _ensure_bluetooth_powered()
        if await _pairing_mode_active():
            raise BluetoothPairingInProgressError(
                "Bluetooth pairing is already in progress"
            )
        alias = await _bluetooth_alias_async()
        await _unpair_all_devices()

        await run_command_async(
            ["systemctl", "start", "bt-timedpair.service"],
            raise_on_fail=True,
            timeout=BLUETOOTH_PAIRING_START_TIMEOUT_SEC,
        )
        if not await _pairing_mode_active():
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
    except asyncio.TimeoutError as exc:
        raise BluetoothPairingError("A Bluetooth command timed out") from exc
    except RunCommandError as exc:
        raise BluetoothPairingError("A Bluetooth command failed") from exc
    finally:
        _pairing_lock.release()
