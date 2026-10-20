"""Tests for P0 network info API additions."""

from unittest.mock import MagicMock, patch

from wlanpi_core.adapters.discovery import LiveInterface
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
    with (
        patch.object(
            network_info_service.discovery,
            "list_namespaced_interfaces",
            return_value=[],
        ),
        patch.object(
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
        ),
    ):
        result = network_info_service.show_wlan_interfaces()

    assert result["wlan0"]["mode"] == "Managed"
    assert WlanInterfaceSummary.model_validate(result["wlan0"]).mode == "Managed"


_NAMESPACED_WLAN1 = [LiveInterface("wlan1", 1, "rcmlo", "managed")]


def test_show_wlan_interfaces_includes_namespaced_interface():
    ns_outputs = {
        ("ethtool", "-i", "wlan1"): "driver: iwlwifi\n",
        ("iw", "wlan1", "info"): (
            "Interface wlan1\n\taddr aa:bb:cc:dd:ee:01\n\tssid wlanpi\n"
            "\ttype managed\n\tchannel 36 (5180 MHz)\n"
        ),
    }

    def fake_ns_exec(cmd, namespace=None):
        assert namespace == "rcmlo"
        return CommandResult(ns_outputs[(cmd[0].rsplit("/", 1)[-1], *cmd[1:])], "", 0)

    with (
        patch.object(
            network_info_service.discovery,
            "list_namespaced_interfaces",
            return_value=_NAMESPACED_WLAN1,
        ),
        patch.object(
            network_info_service,
            "run_command",
            return_value=CommandResult("phy#0\n\tInterface wlan0\n", "", 0),
        ),
        patch.object(network_info_service, "ns_exec", side_effect=fake_ns_exec),
    ):
        result = network_info_service.show_wlan_interfaces()

    summary = WlanInterfaceSummary.model_validate(result["wlan1"])
    assert summary.namespace == "rcmlo"
    assert summary.ssid == "wlanpi"
    assert summary.channel == 36
    assert "namespace" not in result["wlan0"]


def test_show_interfaces_includes_namespaced_interface():
    root = "eth0: flags=4163<UP,BROADCAST>  mtu 1500\n        inet 192.0.2.10  netmask 255.255.255.0\n        RX packets 1\n"
    in_ns = "wlan1: flags=4163<UP,BROADCAST>  mtu 1500\n        inet 192.168.18.223  netmask 255.255.255.0\n        RX packets 1\n"
    with (
        patch.object(
            network_info_service.discovery,
            "list_namespaced_interfaces",
            return_value=_NAMESPACED_WLAN1,
        ),
        patch.object(
            network_info_service,
            "run_command",
            return_value=CommandResult(root, "", 0),
        ),
        patch.object(
            network_info_service, "ns_exec", return_value=CommandResult(in_ns, "", 0)
        ) as ns_exec,
    ):
        result = network_info_service.show_interfaces()

    assert result["eth0"] == {"status": "UP", "ip": "192.0.2.10"}
    assert result["wlan1"] == {
        "status": "UP",
        "ip": "192.168.18.223",
        "namespace": "rcmlo",
    }
    assert ns_exec.call_args.kwargs == {"namespace": "rcmlo"}


def test_network_debug_label_does_not_include_addresses():
    label = network_info_service._section_debug_label(
        "interfaces",
        {"eth0": {"ip": "192.0.2.10", "status": "UP"}},
    )

    assert "192.0.2.10" not in repr(label)
    assert label["interface_names"] == ["eth0"]
