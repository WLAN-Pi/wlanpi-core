"""Tests for P0 network primitive modules."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.network import (
    connections,
    dhcp,
    link_stats,
    lookup,
    routing,
    wlan_drivers,
    wlan_link,
)


@pytest.fixture(autouse=True)
def clear_wlan_driver_inventory_cache():
    wlan_drivers._clear_wlan_driver_inventory_cache()
    yield
    wlan_drivers._clear_wlan_driver_inventory_cache()


def test_get_routing_table_parses_json():
    routes = [{"dst": "default", "gateway": "10.10.0.254", "dev": "eth0"}]
    with patch(
        "wlanpi_core.network.routing.ns_exec",
        return_value=MagicMock(stdout=json.dumps(routes)),
    ):
        result = routing.get_routing_table()

    assert result["namespace"] is None
    assert result["routes"] == routes


def test_get_interfaces_drops_empty_dicts_from_ip_output():
    from wlanpi_core.models.network.common import get_interfaces

    eth0 = {
        "ifindex": 2,
        "ifname": "eth0",
        "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
        "mtu": 1500,
        "qdisc": "fq_codel",
        "operstate": "UP",
        "group": "default",
        "txqlen": 1000,
        "link_type": "ether",
        "address": "52:54:00:00:00:01",
        "broadcast": "ff:ff:ff:ff:ff:ff",
        "addr_info": [],
    }

    def _fake_run(cmd, **kwargs):
        if cmd[0] == "ip":
            return CommandResult(
                stdout=json.dumps([{}, {}, {}, eth0]),
                stderr="",
                return_code=0,
            )
        return CommandResult(stdout="1000", stderr="", return_code=0)

    with patch(
        "wlanpi_core.models.network.common.run_command",
        side_effect=_fake_run,
    ):
        result = get_interfaces(show_type="vlan")

    assert len(result) == 1
    assert result[0].ifname == "eth0"
    assert result[0].link_speed == 1000


def test_get_link_stats_parses_ethtool():
    ethtool_out = (
        "Settings for eth0:\n\tSpeed: 1000Mb/s\n\tDuplex: Full\n\tLink detected: yes\n"
    )
    with patch(
        "wlanpi_core.network.link_stats.ns_exec",
        return_value=MagicMock(stdout=ethtool_out),
    ):
        result = link_stats.get_link_stats("eth0")

    assert result["interface"] == "eth0"
    assert result["speed_mbps"] == 1000
    assert result["duplex"] == "Full"
    assert result["link_detected"] == "yes"


def test_get_wlan_link_parses_connected():
    iw_out = (
        "Connected to 68:51:34:7c:32:13 (on wlan0)\n"
        "\tSSID: PurpleDove\n"
        "\tfreq: 5200.0\n"
        "\tsignal: -48 dBm\n"
        "\trx bitrate: 286.7 MBit/s HE-MCS 11\n"
        "\ttx bitrate: 286.7 MBit/s HE-MCS 11\n"
        "\tRX: 2112666 bytes (22185 packets)\n"
        "\tTX: 104496501 bytes (1980 packets)\n"
    )
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        return_value=MagicMock(stdout=iw_out),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["connected"] is True
    assert result["ssid"] == "PurpleDove"
    assert result["bssid"] == "68:51:34:7c:32:13"
    assert result["freq_mhz"] == 5200.0
    assert result["signal_dbm"] == -48.0
    assert result["rx_bytes"] == 2112666
    assert result["tx_bytes"] == 104496501


def test_get_wlan_link_not_connected():
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        return_value=MagicMock(stdout="Not connected.\n"),
    ):
        result = wlan_link.get_wlan_link("wlan2")

    assert result["connected"] is False
    assert result["ssid"] is None
    assert result["bssid"] is None


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

    with patch(
        "wlanpi_core.network.dhcp.run_command",
        return_value=CommandResult("", "", 1),
    ):
        result = dhcp.get_dhcp_leases(lease_dir=tmp_path)

    assert result["source"] == str(tmp_path)
    assert len(result["leases"]) == 1
    assert result["leases"][0]["interface"] == "eth0"
    assert result["leases"][0]["source_file"] == "dhclient.eth0.leases"


def test_get_dhcp_leases_missing_dir(tmp_path):
    missing = tmp_path / "nope"
    with patch(
        "wlanpi_core.network.dhcp.run_command",
        return_value=CommandResult("", "", 1),
    ):
        result = dhcp.get_dhcp_leases(lease_dir=missing)
    assert result["leases"] == []
    assert "error" in result


def test_get_dhcp_leases_reads_networkmanager():
    output = """GENERAL.DEVICE:eth0
DHCP4.OPTION[1]:ip_address = 192.168.6.63
DHCP4.OPTION[2]:dhcp_server_identifier = 192.168.6.1
DHCP4.OPTION[3]:domain_name_servers = 9.9.9.9 1.0.0.1

GENERAL.DEVICE:wlan0
"""
    with patch(
        "wlanpi_core.network.dhcp.run_command",
        return_value=CommandResult(output, "", 0),
    ):
        result = dhcp.get_dhcp_leases()

    assert result == {
        "leases": [
            {
                "interface": "eth0",
                "ip_address": "192.168.6.63",
                "dhcp_server_identifier": "192.168.6.1",
                "domain_name_servers": "9.9.9.9 1.0.0.1",
            }
        ],
        "source": "NetworkManager",
    }


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


@pytest.mark.asyncio
async def test_renew_interface_dhcp_uses_networkctl():
    status = CommandResult(
        json.dumps(
            {
                "Name": "eth1",
                "AdministrativeState": "configured",
                "NetworkFile": "/etc/systemd/network/eth1.network",
            }
        ),
        "",
        0,
    )
    command = AsyncMock(side_effect=[status, CommandResult("", "", 0)])
    with patch("wlanpi_core.network.dhcp.run_command_async", new=command):
        result = await dhcp.renew_interface_dhcp("eth1")

    assert command.await_args_list[0].args[0] == [
        "/usr/bin/networkctl",
        "status",
        "eth1",
        "--json=short",
        "--no-pager",
    ]
    assert command.await_args_list[1].args[0] == [
        "/usr/bin/networkctl",
        "renew",
        "eth1",
    ]
    assert result["status"] == "renewed"
    assert result["namespace"] is None


@pytest.mark.asyncio
async def test_renew_interface_dhcp_rejects_non_networkd_interface():
    status = CommandResult(
        json.dumps(
            {
                "Name": "eth0",
                "AdministrativeState": "unmanaged",
            }
        ),
        "",
        0,
    )
    command = AsyncMock(return_value=status)
    with patch("wlanpi_core.network.dhcp.run_command_async", new=command):
        with pytest.raises(ValidationError) as exc:
            await dhcp.renew_interface_dhcp("eth0")

    assert exc.value.status_code == 409
    assert command.await_count == 1


@pytest.mark.asyncio
async def test_renew_interface_dhcp_propagates_networkctl_failure():
    status = CommandResult(
        json.dumps(
            {
                "Name": "eth1",
                "AdministrativeState": "configured",
                "NetworkFile": "/etc/systemd/network/eth1.network",
            }
        ),
        "",
        0,
    )
    command = AsyncMock(
        side_effect=[status, RunCommandError("renew failed", return_code=1)]
    )
    with patch("wlanpi_core.network.dhcp.run_command_async", new=command):
        with pytest.raises(RunCommandError):
            await dhcp.renew_interface_dhcp("eth1")


@pytest.mark.asyncio
@pytest.mark.parametrize("iface", ["", "eth0;reboot", "a" * 16, ".."])
async def test_renew_interface_dhcp_rejects_invalid_iface(iface):
    with pytest.raises(ValidationError) as exc:
        await dhcp.renew_interface_dhcp(iface)
    assert exc.value.status_code == 400


def test_resolve_interface_namespace_root():
    with patch(
        "wlanpi_core.network.lookup.network_config.status",
        return_value={
            "root": {"eth0": {"mode": "managed"}},
            "scan_ns": {"wlanpi0": {}},
        },
    ):
        assert lookup.resolve_interface_namespace("eth0") is None
        assert lookup.resolve_interface_namespace("wlanpi0") == "scan_ns"


def test_resolve_interface_namespace_root_falls_back_to_root_link():
    with patch(
        "wlanpi_core.network.lookup.network_config.status",
        return_value={"root": {}},
    ):
        with patch(
            "wlanpi_core.network.lookup._exists_in_root",
            return_value=True,
        ):
            assert lookup.resolve_interface_namespace("eth0") is None


def test_resolve_interface_namespace_fails_closed_on_status_error():
    with patch(
        "wlanpi_core.network.lookup.network_config.status",
        side_effect=RuntimeError("status unavailable"),
    ):
        with pytest.raises(ValidationError) as exc:
            lookup.resolve_interface_namespace("eth0")

    assert exc.value.status_code == 503


def test_resolve_interface_namespace_rejects_missing_interface():
    with patch(
        "wlanpi_core.network.lookup.network_config.status",
        return_value={"root": {"eth0": {}}, "scan_ns": {"wlanpi0": {}}},
    ):
        with patch(
            "wlanpi_core.network.lookup._exists_in_root",
            return_value=False,
        ):
            with pytest.raises(ValidationError) as exc:
                lookup.resolve_interface_namespace("eth9")

    assert exc.value.status_code == 404


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
    assert result["interfaces_scanned"] == 2


def test_bus_from_sysfs_path_pci_bdf():
    path = Path("/sys/class/ieee80211/phy0/device")
    with patch.object(
        Path,
        "resolve",
        return_value=Path("/sys/devices/pci0000:00/0000:00:00.0/0000:01:00.0"),
    ):
        assert wlan_drivers._bus_from_sysfs_path(path) == "pci"


def test_bus_from_sysfs_path_usb():
    path = Path("/sys/class/ieee80211/phy1/device")
    with patch.object(
        Path,
        "resolve",
        return_value=Path("/sys/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0"),
    ):
        assert wlan_drivers._bus_from_sysfs_path(path) == "usb"


def test_get_pci_wlan_drivers():
    with patch(
        "wlanpi_core.network.wlan_drivers.run_command",
        return_value=MagicMock(
            stdout="0000:01:00.0 Wireless controller: Example PCI Wi-Fi\n"
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


def test_wlan_driver_inventory_cache_is_shared_within_ttl():
    inventory = {
        "adapters": [
            {"interface": "wlan0", "driver": "ath9k_htc", "bus": "usb"},
            {"interface": "wlan1", "driver": "brcmfmac", "bus": "pci"},
        ],
        "pci_devices": [
            {"pci_id": "0000:01:00.0", "description": "Wireless controller"}
        ],
        "interfaces_scanned": 2,
    }
    with patch.object(
        wlan_drivers,
        "_collect_wlan_driver_inventory",
        return_value=inventory,
    ) as collect:
        with patch.object(wlan_drivers.time, "monotonic", return_value=100.0):
            usb = wlan_drivers.get_usb_wlan_drivers()
            pci = wlan_drivers.get_pci_wlan_drivers()

    collect.assert_called_once_with()
    assert [adapter["interface"] for adapter in usb["adapters"]] == ["wlan0"]
    assert [adapter["interface"] for adapter in pci["adapters"]] == ["wlan1"]


def test_wlan_driver_inventory_cache_expires_after_two_seconds():
    inventory = {"adapters": [], "pci_devices": [], "interfaces_scanned": 0}
    with patch.object(
        wlan_drivers,
        "_collect_wlan_driver_inventory",
        return_value=inventory,
    ) as collect:
        with patch.object(
            wlan_drivers.time,
            "monotonic",
            side_effect=[100.0, 100.0, 102.0, 102.0],
        ):
            wlan_drivers.get_usb_wlan_drivers()
            wlan_drivers.get_usb_wlan_drivers()

    assert collect.call_count == 2
