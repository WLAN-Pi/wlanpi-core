"""Tests for P0 network primitive modules."""

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wlanpi_core.adapters.discovery import LiveInterface
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.network.namespace.namespace_errors import (
    NetworkNamespaceError,
)
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
from wlanpi_core.schemas.network import WlanLink


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


# Captured on a WLAN Pi (kernel 7.2, iw 6.17) associated to an Aruba 755 MLD.
# iw link lists all three set-up links in kernel BSS-list order (0, 2, 1),
# so the last freq: line (5220) is not the link in use.
_MLO_IW_LINK = (
    "Connected to 68:51:34:7c:32:05 (on wlan0)\n"
    "\tSSID: wlanpi\n"
    "\tLink 0 BSSID 68:51:34:7c:32:05\n"
    "\t\tfreq: 6295.0\n"
    "\tLink 2 BSSID 68:51:34:7c:31:f5\n"
    "\t\tfreq: 2462.0\n"
    "\tLink 1 BSSID 68:51:34:7c:32:15\n"
    "\t\tfreq: 5220.0\n"
    "MLD 68:51:34:7c:32:05 stats:\n"
    "\tRX: 1434961664 bytes (932187 packets)\n"
    "\tTX: 5397105 bytes (61744 packets)\n"
    "\tsignal: 0 dBm\n"
    "\trx bitrate: 1441.1 MBit/s 80MHz EHT-MCS 13 EHT-NSS 2 EHT-GI 0\n"
    "\ttx bitrate: 1441.1 MBit/s 80MHz EHT-MCS 13 EHT-NSS 2 EHT-GI 0\n"
)
_MLO_INFO_HEAD = (
    "Interface wlan0\n"
    "\tifindex 2\n"
    "\taddr e8:bf:b8:73:9a:48\n"
    "\tssid wlanpi\n"
    "\ttype managed\n"
    "\twiphy 2\n"
    "\tMLD with links:\n"
)
_LINK0_ACTIVE = (
    "\t - link ID  0 link addr 46:4e:e4:c6:8a:7e\n"
    "\t   channel 69 (6295 MHz), width: 80 MHz, center1: 6305 MHz\n"
    "\t   txpower 22.00 dBm\n"
)
_LINK1_ACTIVE = (
    "\t - link ID  1 link addr 4e:66:24:b6:db:12\n"
    "\t   channel 44 (5220 MHz), width: 20 MHz, center1: 5220 MHz\n"
    "\t   txpower 22.00 dBm\n"
)
_STATION = (
    "Station 68:51:34:7c:32:05 (on wlan0)\n"
    "\tsignal:  \t0 dBm\n"
    "\tsignal avg:\t-43 dBm\n"
    "\tbeacon signal avg:\t-42 dBm\n"
)


def _iw_by_command(outputs):
    """Return an ns_exec side effect keyed on the iw subcommand."""

    def run(cmd, namespace=None):
        key = cmd[3]
        if key == "station":
            assert cmd[4:] == ["get", "68:51:34:7c:32:05"]
        if isinstance(outputs[key], Exception):
            raise outputs[key]
        return MagicMock(stdout=outputs[key])

    return run


def _links(result):
    return {(x["link_id"], x["freq_mhz"], x["active"]) for x in result["links"]}


def test_get_wlan_link_mlo_reports_active_link_not_last_listed():
    info = (
        _MLO_INFO_HEAD
        + _LINK0_ACTIVE
        + "\t - link ID  1 link addr 4e:66:24:b6:db:12\n"
        + "\t - link ID  2 link addr 0e:30:c8:74:31:ee\n"
    )
    outputs = {"link": _MLO_IW_LINK, "info": info, "station": _STATION}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0", namespace="rcmlo")

    assert result["freq_mhz"] == 6295.0
    assert result["bssid"] == "68:51:34:7c:32:05"
    assert _links(result) == {
        (0, 6295.0, True),
        (2, 2462.0, False),
        (1, 5220.0, False),
    }
    # MLD-level signal is ignored with several set-up links; the beacon
    # average follows the active link.
    assert result["signal_dbm"] == -42.0


def test_get_wlan_link_mlo_follows_active_link_change():
    info = (
        _MLO_INFO_HEAD
        + "\t - link ID  0 link addr 46:4e:e4:c6:8a:7e\n"
        + _LINK1_ACTIVE
        + "\t - link ID  2 link addr 0e:30:c8:74:31:ee\n"
    )
    outputs = {"link": _MLO_IW_LINK, "info": info, "station": _STATION}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["freq_mhz"] == 5220.0
    assert (1, 5220.0, True) in _links(result)


def test_get_wlan_link_mlo_two_active_links_has_no_single_freq():
    # ath12k STR: two links active, every signal field 0.
    info = (
        _MLO_INFO_HEAD
        + _LINK0_ACTIVE
        + _LINK1_ACTIVE
        + "\t - link ID  2 link addr 0e:30:c8:74:31:ee\n"
    )
    station = (
        "Station 68:51:34:7c:32:05 (on wlan0)\n"
        "\tsignal:  \t0 dBm\n"
        "\tsignal avg:\t0 dBm\n"
        "\tbeacon signal avg:\t0 dBm\n"
    )
    outputs = {"link": _MLO_IW_LINK, "info": info, "station": station}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["freq_mhz"] is None
    assert {x["link_id"] for x in result["links"] if x["active"]} == {0, 1}
    assert result["signal_dbm"] is None


def test_get_wlan_link_mlo_info_failure_reports_unknown_not_guess():
    outputs = {
        "link": _MLO_IW_LINK,
        "info": RunCommandError("iw failed", 1),
        "station": RunCommandError("iw failed", 1),
    }
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["connected"] is True
    assert result["freq_mhz"] is None
    assert all(x["active"] is None for x in result["links"])
    assert result["signal_dbm"] is None


@pytest.mark.parametrize("failing", ["info", "station"])
def test_get_wlan_link_mlo_supplementary_timeout_is_not_fatal(failing):
    info = _MLO_INFO_HEAD + _LINK0_ACTIVE
    outputs = {"link": _MLO_IW_LINK, "info": info, "station": _STATION}
    outputs[failing] = subprocess.TimeoutExpired(cmd="iw", timeout=10)
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["connected"] is True
    if failing == "info":
        assert result["freq_mhz"] is None
        assert result["signal_dbm"] == -42.0
    else:
        assert result["freq_mhz"] == 6295.0
        assert result["signal_dbm"] is None


def test_get_wlan_link_station_signal_ignores_per_link_blocks():
    info = _MLO_INFO_HEAD + _LINK0_ACTIVE
    station = (
        "Station 68:51:34:7c:32:05 (on wlan0)\n"
        "\tsignal avg:\t0 dBm\n"
        "\tbeacon signal avg:\t-42 dBm\n"
        "\tLink 2:\n"
        "\t\taddress: 68:51:34:7c:31:f5\n"
        "\t\tsignal avg:\t-70 dBm\n"
    )
    outputs = {"link": _MLO_IW_LINK, "info": info, "station": station}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["signal_dbm"] == -42.0


def test_get_wlan_link_authenticated_only_is_not_connected():
    iw_out = "Authenticated with 68:51:34:7c:32:05 (on wlan0)\nNot connected.\n"
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        return_value=MagicMock(stdout=iw_out),
    ) as execute:
        result = wlan_link.get_wlan_link("wlan0")

    assert result["connected"] is False
    assert result["signal_dbm"] is None
    assert execute.call_count == 1


def test_get_wlan_link_ibss_skips_station_fallback():
    iw_out = "Joined IBSS 02:11:22:33:44:55 (on wlan0)\n\tfreq: 2412.0\n"
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        return_value=MagicMock(stdout=iw_out),
    ) as execute:
        result = wlan_link.get_wlan_link("wlan0")

    assert result["connected"] is True
    assert result["freq_mhz"] == 2412.0
    assert result["signal_dbm"] is None
    assert execute.call_count == 1


def test_get_wlan_link_non_mlo_runs_only_iw_link():
    iw_out = (
        "Connected to 68:51:34:7c:32:13 (on wlan0)\n"
        "\tSSID: PurpleDove\n"
        "\tfreq: 5200.0\n"
        "\tsignal: -48 dBm\n"
    )
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        return_value=MagicMock(stdout=iw_out),
    ) as execute:
        result = wlan_link.get_wlan_link("wlan0")

    assert execute.call_count == 1
    assert result["freq_mhz"] == 5200.0
    assert result["signal_dbm"] == -48.0
    assert result["links"] == []


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


def _live(name, netns=None, phy_index=0):
    return LiveInterface(name, phy_index, netns, "managed")


def test_get_usb_wlan_drivers_filters_bus():
    with patch(
        "wlanpi_core.network.wlan_drivers.discovery.list_interfaces_all_namespaces",
        return_value=[_live("wlan0"), _live("wlanpi0")],
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
            "wlanpi_core.network.wlan_drivers.discovery.list_interfaces_all_namespaces",
            return_value=[_live("wlanpi0")],
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
    assert result["adapters"][0]["namespace"] is None


def test_wlan_driver_inventory_includes_namespaced_interfaces():
    """A radio moved into a namespace stays listed, with its namespace (#333)."""
    with patch.object(wlan_drivers, "run_command", return_value=MagicMock(stdout="")):
        with patch.object(
            wlan_drivers.discovery,
            "list_interfaces_all_namespaces",
            return_value=[_live("wlan1"), _live("wlan2", "nsvis", 1)],
        ):
            with patch.object(
                wlan_drivers, "_bus_for_interface", return_value="pci"
            ) as bus:
                with patch.object(
                    wlan_drivers, "_driver_for_interface", return_value="mt7921e"
                ) as driver:
                    result = wlan_drivers._collect_wlan_driver_inventory()

    assert [(a["interface"], a["namespace"]) for a in result["adapters"]] == [
        ("wlan1", None),
        ("wlan2", "nsvis"),
    ]
    assert result["interfaces_scanned"] == 2
    bus.assert_any_call("wlan2", "nsvis")
    driver.assert_any_call("wlan2", "nsvis")


def test_wlan_driver_inventory_falls_back_to_root_without_namespaces():
    with patch.object(wlan_drivers, "run_command", return_value=MagicMock(stdout="")):
        with patch.object(
            wlan_drivers.discovery,
            "list_interfaces_all_namespaces",
            side_effect=NetworkNamespaceError("ip netns list failed"),
        ):
            with patch.object(
                wlan_drivers.discovery, "list_interfaces", return_value=["wlan0"]
            ):
                with patch.object(
                    wlan_drivers, "_bus_for_interface", return_value="usb"
                ):
                    with patch.object(
                        wlan_drivers, "_driver_for_interface", return_value="mt7921u"
                    ):
                        result = wlan_drivers._collect_wlan_driver_inventory()

    assert result["adapters"] == [
        {"interface": "wlan0", "namespace": None, "driver": "mt7921u", "bus": "usb"}
    ]


def test_bus_and_driver_for_namespaced_interface_run_in_the_namespace():
    """The phy's sysfs is only visible in its namespace, so iw/readlink run there."""
    outputs = {
        ("iw", "dev", "wlan2", "info"): "Interface wlan2\n\twiphy 1\n",
        ("readlink", "-f", "/sys/class/ieee80211/phy1/device"): (
            "/sys/devices/platform/axi/1000110000.pcie/pci0000:00/0000:01:00.0\n"
        ),
        ("/sbin/ethtool", "-i", "wlan2"): "driver: mt7921e\n",
    }

    def fake_ns_exec(cmd, namespace, no_output, raise_on_fail):
        assert namespace == "nsvis"
        assert raise_on_fail is False
        return MagicMock(stdout=outputs[tuple(cmd)])

    with patch.object(wlan_drivers, "IW_FILE", "iw"):
        with patch.object(wlan_drivers, "ETHTOOL_FILE", "/sbin/ethtool"):
            with patch.object(wlan_drivers, "ns_exec", side_effect=fake_ns_exec):
                with patch.object(wlan_drivers, "run_command") as root:
                    assert wlan_drivers._bus_for_interface("wlan2", "nsvis") == "pci"
                    assert (
                        wlan_drivers._driver_for_interface("wlan2", "nsvis")
                        == "mt7921e"
                    )

    root.assert_not_called()


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


def test_get_wlan_link_status_words_in_ssid_do_not_change_state():
    iw_out = (
        "Connected to 68:51:34:7c:32:13 (on wlan0)\n"
        "\tSSID: Not connected\n"
        "\tfreq: 5200.0\n"
        "\tsignal: -48 dBm\n"
    )
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        return_value=MagicMock(stdout=iw_out),
    ):
        result = wlan_link.get_wlan_link("wlan0")
    assert result["connected"] is True
    assert result["ssid"] == "Not connected"

    ibss = "Joined IBSS 02:11:22:33:44:55 (on wlan0)\n\tSSID: Connected to x\n"
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        return_value=MagicMock(stdout=ibss),
    ) as execute:
        result = wlan_link.get_wlan_link("wlan0")
    assert result["connected"] is True
    assert result["bssid"] is None
    assert execute.call_count == 1


def test_get_wlan_link_mlo_ignores_stale_nonzero_mld_signal():
    # Captured on BE200: 5 GHz active, 6 GHz idle. The MLD signal (-41) is
    # the 6 GHz link's last reading; the 5 GHz truth is -47 (beacon avg,
    # and every field on a single-link association to the same BSS).
    iw_link = _MLO_IW_LINK.replace("signal: 0 dBm", "signal: -41 dBm")
    info = (
        _MLO_INFO_HEAD
        + "\t - link ID  0 link addr 46:4e:e4:c6:8a:7e\n"
        + _LINK1_ACTIVE
        + "\t - link ID  2 link addr 0e:30:c8:74:31:ee\n"
    )
    station = (
        "Station 68:51:34:7c:32:05 (on wlan0)\n"
        "\tsignal:  \t-41 dBm\n"
        "\tbeacon signal avg:\t-47 dBm\n"
    )
    outputs = {"link": iw_link, "info": info, "station": station}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["freq_mhz"] == 5220.0
    assert result["signal_dbm"] == -47.0


def test_get_wlan_link_single_link_mld_keeps_iw_link_signal():
    iw_link = (
        "Connected to 68:51:34:7c:32:16 (on wlan0)\n"
        "\tSSID: wlanpi-psk\n"
        "\tLink 0 BSSID 68:51:34:7c:32:16\n"
        "\t\tfreq: 5220.0\n"
        "MLD 68:51:34:7c:32:16 stats:\n"
        "\tsignal: -47 dBm\n"
    )
    info = _MLO_INFO_HEAD + _LINK1_ACTIVE.replace("ID  1", "ID  0")
    calls = []

    def run(cmd, namespace=None):
        calls.append(cmd[3])
        return MagicMock(stdout={"link": iw_link, "info": info}[cmd[3]])

    with patch("wlanpi_core.network.wlan_link.ns_exec", side_effect=run):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["freq_mhz"] == 5220.0
    assert result["signal_dbm"] == -47.0
    assert calls == ["link", "info", "link"]


@pytest.mark.parametrize(
    ("station_lines", "expected"),
    [
        ("\tsignal avg:\t-44 dBm\n\tbeacon signal avg:\t-40 dBm\n", -44.0),
        ("\tsignal avg:\t0 dBm\n\tbeacon signal avg:\t-40 dBm\n", -40.0),
        ("\tsignal avg:\t0 dBm\n\tbeacon signal avg:\t0 dBm\n", None),
        ("", None),
    ],
)
def test_get_wlan_link_single_link_zero_signal_falls_back(station_lines, expected):
    # iw link signal 0 = no reading yet: signal avg, then beacon avg, else null.
    iw_out = (
        "Connected to 68:51:34:7c:32:05 (on wlan0)\n"
        "\tSSID: wlanpi-wifi6\n"
        "\tfreq: 5220.0\n"
        "\tsignal: 0 dBm\n"
    )
    station = "Station 68:51:34:7c:32:05 (on wlan0)\n" + station_lines
    outputs = {"link": iw_out, "station": station}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["freq_mhz"] == 5220.0
    assert result["signal_dbm"] == expected


def test_get_wlan_link_mlo_without_beacon_avg_uses_signal_avg():
    # mt7925u: no beacon signal avg line; signal avg is the fallback.
    info = _MLO_INFO_HEAD + _LINK0_ACTIVE + _LINK1_ACTIVE
    station = (
        "Station 68:51:34:7c:32:05 (on wlan0)\n"
        "\tsignal:  \t-34 dBm\n"
        "\tsignal avg:\t-36 dBm\n"
    )
    outputs = {"link": _MLO_IW_LINK, "info": info, "station": station}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["freq_mhz"] is None
    assert result["signal_dbm"] == -36.0


def test_wlan_link_response_model_serializes_links():
    info = _MLO_INFO_HEAD + _LINK0_ACTIVE + "\t - link ID  1\n\t - link ID  2\n"
    outputs = {"link": _MLO_IW_LINK, "info": info, "station": _STATION}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    body = WlanLink.model_validate(result).model_dump(mode="json")
    assert body["links"] == [
        {
            "link_id": 0,
            "bssid": "68:51:34:7c:32:05",
            "freq_mhz": 6295.0,
            "active": True,
            "local_addr": "46:4e:e4:c6:8a:7e",
            "width_mhz": 80,
            "center1_mhz": 6305,
        },
        {
            "link_id": 2,
            "bssid": "68:51:34:7c:31:f5",
            "freq_mhz": 2462.0,
            "active": False,
            "local_addr": None,
            "width_mhz": None,
            "center1_mhz": None,
        },
        {
            "link_id": 1,
            "bssid": "68:51:34:7c:32:15",
            "freq_mhz": 5220.0,
            "active": False,
            "local_addr": None,
            "width_mhz": None,
            "center1_mhz": None,
        },
    ]
    assert body["freq_mhz"] == 6295.0
    assert body["signal_dbm"] == -42.0

    non_mlo = WlanLink.model_validate({"interface": "wlan0", "connected": False})
    assert non_mlo.model_dump(mode="json")["links"] == []


def test_get_wlan_link_mlo_reports_link_addresses_and_active_width():
    # Every set-up link carries this station's own address; only active links
    # have a channel, so only they get a width and center frequency.
    info = (
        _MLO_INFO_HEAD
        + _LINK0_ACTIVE
        + "\t - link ID  1 link addr 4E:66:24:B6:DB:12\n"
        + "\t - link ID  2 link addr 0e:30:c8:74:31:ee\n"
    )
    outputs = {"link": _MLO_IW_LINK, "info": info, "station": _STATION}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    by_id = {x["link_id"]: x for x in result["links"]}
    assert by_id[0]["local_addr"] == "46:4e:e4:c6:8a:7e"
    assert (by_id[0]["width_mhz"], by_id[0]["center1_mhz"]) == (80, 6305)
    assert by_id[1]["local_addr"] == "4e:66:24:b6:db:12"
    assert "width_mhz" not in by_id[1]
    assert by_id[2]["local_addr"] == "0e:30:c8:74:31:ee"
    assert "width_mhz" not in by_id[2]


def test_get_wlan_link_mlo_info_failure_has_no_link_details():
    outputs = {
        "link": _MLO_IW_LINK,
        "info": RunCommandError("iw failed", 1),
        "station": _STATION,
    }
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert all("local_addr" not in x for x in result["links"])


# The same client after a reassociation to the 5 GHz link alone.
_MLO_IW_LINK_5G_ONLY = (
    "Connected to 68:51:34:7c:32:05 (on wlan0)\n"
    "\tSSID: wlanpi\n"
    "\tLink 1 BSSID 68:51:34:7c:32:15\n"
    "\t\tfreq: 5220.0\n"
)


@pytest.mark.parametrize("second", [_MLO_IW_LINK_5G_ONLY, "Not connected.\n"])
def test_get_wlan_link_mlo_association_change_mid_request_is_unknown(second):
    # iw info already shows the new association (only link 1, active), while
    # the first iw link still lists the old links.
    reads = iter([_MLO_IW_LINK, second])
    outputs = {
        "info": _MLO_INFO_HEAD + _LINK1_ACTIVE,
        "station": _STATION,
    }

    def run(cmd, namespace=None):
        if cmd[3] == "link":
            return MagicMock(stdout=next(reads))
        return _iw_by_command(outputs)(cmd, namespace)

    with patch("wlanpi_core.network.wlan_link.ns_exec", side_effect=run):
        result = wlan_link.get_wlan_link("wlan0")

    assert result["connected"] is True
    assert result["freq_mhz"] is None
    assert [x["active"] for x in result["links"]] == [None, None, None]
    assert all(
        set(x) == {"link_id", "bssid", "freq_mhz", "active"} for x in result["links"]
    )


def test_get_wlan_link_mlo_link_missing_from_info_is_unknown():
    info = (
        _MLO_INFO_HEAD + _LINK0_ACTIVE + "\t - link ID  1 link addr 4e:66:24:b6:db:12\n"
    )
    outputs = {"link": _MLO_IW_LINK, "info": info, "station": _STATION}
    with patch(
        "wlanpi_core.network.wlan_link.ns_exec",
        side_effect=_iw_by_command(outputs),
    ):
        result = wlan_link.get_wlan_link("wlan0")

    assert _links(result) == {
        (0, 6295.0, True),
        (1, 5220.0, False),
        (2, 2462.0, None),
    }


def test_parse_link_details_keys_channel_to_its_own_link():
    # A link line without "link addr" must still start a new link, so the
    # channel below it is not credited to the previous one.
    info = (
        _MLO_INFO_HEAD
        + "\t - link ID  1 link addr 4e:66:24:b6:db:12\n"
        + "\t - link ID  2\n"
        + "\t   channel 11 (2462 MHz), width: 20 MHz (no HT), center1: 2462 MHz\n"
    )

    details = wlan_link._parse_link_details(info)

    assert details == {
        1: {"local_addr": "4e:66:24:b6:db:12"},
        2: {"width_mhz": 20, "center1_mhz": 2462},
    }
