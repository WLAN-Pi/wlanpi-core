"""Tests for P0 network primitive modules."""
import json
from unittest.mock import MagicMock, patch

import pytest

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.network import (
    dhcp,
    link_stats,
    lookup,
    routing,
    connections,
    wlan_drivers,
)


def test_get_routing_table_parses_json():
    routes = [{"dst": "default", "gateway": "10.10.0.254", "dev": "eth0"}]
    with patch(
        "wlanpi_core.network.routing.ns_exec",
        return_value=MagicMock(stdout=json.dumps(routes)),
    ):
        result = routing.get_routing_table()

    assert result["namespace"] is None
    assert result["routes"] == routes


def test_get_link_stats_parses_ethtool():
    ethtool_out = "Settings for eth0:\n\tSpeed: 1000Mb/s\n\tDuplex: Full\n\tLink detected: yes\n"
    with patch(
        "wlanpi_core.network.link_stats.ns_exec",
        return_value=MagicMock(stdout=ethtool_out),
    ):
        result = link_stats.get_link_stats("eth0")

    assert result["interface"] == "eth0"
    assert result["speed_mbps"] == 1000
    assert result["duplex"] == "Full"
    assert result["link_detected"] == "yes"


def test_get_tcp_connections_parses_ss():
    with patch(
        "wlanpi_core.network.connections.ns_exec",
        return_value=MagicMock(stdout="ESTAB 0 0 10.0.0.1:22 10.0.0.2:50115\n"),
    ):
        result = connections.get_tcp_connections()

    assert len(result["connections"]) == 1
    assert result["connections"][0]["protocol"] == "tcp"
    assert result["connections"][0]["local"] == "10.0.0.1:22"


def test_get_udp_connections_parses_ss():
    with patch(
        "wlanpi_core.network.connections.ns_exec",
        return_value=MagicMock(stdout="UNCONN 0 0 0.0.0.0:68 0.0.0.0:*\n"),
    ):
        result = connections.get_udp_connections()

    assert len(result["connections"]) == 1
    assert result["connections"][0]["protocol"] == "udp"


def test_get_dhcp_leases_reads_files(tmp_path):
    lease_file = tmp_path / "dhclient.eth0.leases"
    lease_file.write_text(
        'lease {\n  interface "eth0";\n  fixed-address 10.10.0.163;\n}\n'
    )

    result = dhcp.get_dhcp_leases(lease_dir=tmp_path)

    assert result["source"] == str(tmp_path)
    assert len(result["leases"]) == 1
    assert result["leases"][0]["interface"] == "eth0"
    assert result["leases"][0]["source_file"] == "dhclient.eth0.leases"


def test_get_dhcp_leases_missing_dir(tmp_path):
    missing = tmp_path / "nope"
    result = dhcp.get_dhcp_leases(lease_dir=missing)
    assert result["leases"] == []
    assert "error" in result


def test_parse_lease_blocks():
    text = """
lease {
  interface "eth0";
  fixed-address 10.10.0.163;
  option routers 10.10.0.254;
}
"""
    leases = dhcp._parse_lease_blocks(text)
    assert leases[0]["interface"] == "eth0"
    assert leases[0]["fixed_address"] == "10.10.0.163"
    assert leases[0]["option_routers"] == "10.10.0.254"


def test_renew_interface_dhcp_uses_namespace_lookup():
    with patch(
        "wlanpi_core.network.dhcp.resolve_interface_namespace",
        return_value="scan_ns",
    ):
        with patch(
            "wlanpi_core.network.dhcp.restart_dhcp_with_timeout"
        ) as restart:
            result = dhcp.renew_interface_dhcp("wlanpi0")

    restart.assert_called_once_with("wlanpi0", "scan_ns", timeout=15)
    assert result["status"] == "renewed"
    assert result["namespace"] == "scan_ns"


def test_renew_interface_dhcp_requires_iface():
    with pytest.raises(ValidationError):
        dhcp.renew_interface_dhcp("")


def test_resolve_interface_namespace_root():
    with patch(
        "wlanpi_core.network.lookup.network_config.status",
        return_value={"root": {"eth0": {"mode": "managed"}}, "scan_ns": {"wlanpi0": {}}},
    ):
        assert lookup.resolve_interface_namespace("eth0") is None
        assert lookup.resolve_interface_namespace("wlanpi0") == "scan_ns"


def test_get_usb_wlan_drivers_filters_bus():
    with patch(
        "wlanpi_core.network.wlan_drivers.discovery.list_interfaces",
        return_value=["wlan0", "wlanpi0"],
    ):
        with patch(
            "wlanpi_core.network.wlan_drivers._bus_for_interface",
            side_effect=["usb", "pci"],
        ):
            with patch(
                "wlanpi_core.network.wlan_drivers._driver_for_interface",
                return_value="ath9k_htc",
            ):
                result = wlan_drivers.get_usb_wlan_drivers()

    assert len(result["adapters"]) == 1
    assert result["adapters"][0]["interface"] == "wlan0"
    assert result["adapters"][0]["bus"] == "usb"


def test_get_pci_wlan_drivers():
    with patch(
        "wlanpi_core.network.wlan_drivers.run_command",
        return_value=MagicMock(
            stdout="0000:01:00.0 Wireless controller: Example PCI WiFi\n"
        ),
    ):
        with patch(
            "wlanpi_core.network.wlan_drivers.discovery.list_interfaces",
            return_value=["wlanpi0"],
        ):
            with patch(
                "wlanpi_core.network.wlan_drivers._bus_for_interface",
                return_value="pci",
            ):
                with patch(
                    "wlanpi_core.network.wlan_drivers._driver_for_interface",
                    return_value="brcmfmac",
                ):
                    result = wlan_drivers.get_pci_wlan_drivers()

    assert len(result["pci_devices"]) == 1
    assert result["adapters"][0]["interface"] == "wlanpi0"
    assert result["adapters"][0]["driver"] == "brcmfmac"
