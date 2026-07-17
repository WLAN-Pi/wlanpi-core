import subprocess

from wlanpi_core.cli import network_config
from wlanpi_core.core import system


def test_system_manager_bounds_capture_command(mocker):
    manager = object.__new__(system.SystemManager)
    check_output = mocker.patch.object(
        system.subprocess,
        "check_output",
        return_value=b"result\n",
    )

    assert manager._run(["command"], capture_output=True) == "result"

    check_output.assert_called_once_with(
        ["command"],
        stderr=subprocess.DEVNULL,
        timeout=system._SYSTEM_COMMAND_TIMEOUT_SEC,
    )


def test_system_manager_timeout_fails_closed(mocker):
    manager = object.__new__(system.SystemManager)
    mocker.patch.object(
        system.subprocess,
        "check_call",
        side_effect=subprocess.TimeoutExpired(["command"], 10),
    )

    assert manager._run(["command"]) is False


def test_network_config_interface_probe_has_timeout(mocker):
    cli = network_config.NetworkConfigCLI()
    run = mocker.patch.object(
        network_config.subprocess,
        "run",
        return_value=mocker.Mock(stdout="2: wlan0: <UP>\n"),
    )

    assert cli.get_available_interfaces() == ["wlan0"]

    run.assert_called_once_with(
        ["ip", "link", "show"],
        capture_output=True,
        text=True,
        check=True,
        timeout=network_config.COMMAND_TIMEOUT_SEC,
    )
