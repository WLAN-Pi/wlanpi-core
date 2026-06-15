"""Unit tests for blinker and bluetooth pair services."""
from unittest.mock import MagicMock

import pytest

from wlanpi_core.services import bluetooth_service, utils_service


def test_port_blinker_status_not_running(mocker):
    mocker.patch.object(
        utils_service.subprocess,
        "run",
        return_value=MagicMock(returncode=1, stdout=""),
    )
    assert utils_service.port_blinker_status() == {"active": False}


def test_start_port_blinker_missing_script(mocker, tmp_path):
    mocker.patch.object(utils_service, "BLINKER_FILE", str(tmp_path / "missing.sh"))
    mocker.patch.object(utils_service, "_blinker_script_running", return_value=False)
    with pytest.raises(FileNotFoundError):
        utils_service.start_port_blinker()


def test_bluetooth_pair_discoverable(mocker):
    mocker.patch.object(bluetooth_service, "bluetooth_present", return_value=True)
    mocker.patch.object(bluetooth_service, "bluetooth_set_power", return_value=True)
    mocker.patch.object(bluetooth_service, "_unpair_all_devices")
    mocker.patch.object(bluetooth_service, "bluetooth_paired_devices", return_value=None)
    mocker.patch.object(bluetooth_service, "bluetooth_alias", return_value="wlanpi-test")
    mocker.patch.object(bluetooth_service, "run_command", return_value=MagicMock(stdout=""))

    result = bluetooth_service.bluetooth_pair()
    assert result["status"] == "discoverable"
    assert result["alias"] == "wlanpi-test"
