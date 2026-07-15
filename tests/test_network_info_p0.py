"""Tests for P0 network info API additions."""
from unittest.mock import MagicMock, patch

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.schemas.network_info.network_info import WlanInterfaceSummary
from wlanpi_core.services import network_info_service


def test_show_publicip_ipv6():
    with patch.object(
        network_info_service,
        "run_command",
        return_value=MagicMock(stdout="2001:db8::1\nISP Example\n"),
    ):
        result = network_info_service.show_publicip(ip_version=6)

    assert result["info"] == ["2001:db8::1", "ISP Example"]
    assert "error" not in result or result.get("error") is None


def test_show_publicip_maps_run_command_failure():
    with patch.object(
        network_info_service,
        "run_command",
        side_effect=RunCommandError("probe failed", 1),
    ):
        result = network_info_service.show_publicip()

    assert result == {"info": [], "error": "Failed to detect public IP address"}


def test_show_wlan_interfaces_emits_mode_as_string():
    with patch.object(
        network_info_service,
        "run_command",
        side_effect=[
            CommandResult("phy#0\n\tInterface wlan0\n", "", 0),
            CommandResult("driver: iwlwifi\n", "", 0),
            CommandResult(
                "Interface wlan0\n\taddr aa:bb:cc:dd:ee:ff\n"
                "\ttype managed\n\tchannel 36 (5180 MHz)\n",
                "",
                0,
            ),
        ],
    ):
        result = network_info_service.show_wlan_interfaces()

    assert result["wlan0"]["mode"] == "Managed"
    assert WlanInterfaceSummary.model_validate(result["wlan0"]).mode == "Managed"


def test_network_debug_label_does_not_include_addresses():
    label = network_info_service._section_debug_label(
        "interfaces",
        {"eth0": {"ip": "192.0.2.10", "status": "UP"}},
    )

    assert "192.0.2.10" not in repr(label)
    assert label["interface_names"] == ["eth0"]
