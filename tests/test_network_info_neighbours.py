import json

import pytest

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.services import network_info_service

LLDP_NEIGHBOUR = {
    "name": "eth0",
    "via": "LLDP",
    "chassis": [
        {
            "id": [{"type": "mac", "value": "9c:05:d6:c2:1d:fc"}],
            "name": [{"value": "Lab24ProMax"}],
            "descr": [{"value": "UBNT-USPM24P"}],
            "mgmt-ip": [{"value": "10.254.102.1"}],
        }
    ],
    "port": [
        {
            "id": [{"type": "local", "value": "Port 1"}],
            "descr": [{"value": "Uplink to core"}],
        }
    ],
    "vlan": [{"vlan-id": "102", "pvid": True}],
}

CDP_NEIGHBOUR = {
    "name": "eth0",
    "via": "CDPv2",
    "chassis": [
        {
            "name": [{"value": "cisco-sw01"}],
            "descr": [{"value": "cisco WS-C3560-8PC\nrunning IOS"}],
            "mgmt-ip": [{"value": "192.168.20.1"}],
        }
    ],
    "port": [{"id": [{"type": "ifname", "value": "FastEthernet0/8"}]}],
    "vlan": [{"vlan-id": "20", "pvid": True}],
}


def _mock_lldpctl(monkeypatch, interfaces):
    payload = {"lldp": [{"interface": interfaces} if interfaces else {}]}

    def fake_run_command(cmd, **kwargs):
        assert cmd[-2:] == ["-f", "json0"]
        return CommandResult(json.dumps(payload), "", 0)

    monkeypatch.setattr(network_info_service, "run_command", fake_run_command)


def test_show_lldp_neighbour_renders_legacy_lines(monkeypatch):
    _mock_lldpctl(monkeypatch, [LLDP_NEIGHBOUR, CDP_NEIGHBOUR])

    assert network_info_service.show_lldp_neighbour() == {
        "info": [
            "Name: Lab24ProMax",
            "Port: Port 1",
            "Desc: Uplink to core",
            "IP: 10.254.102.1",
            "Native VLAN: 102",
            "Model: UBNT-USPM24P",
        ]
    }


def test_show_cdp_neighbour_selects_cdp_and_truncates_model(monkeypatch):
    _mock_lldpctl(monkeypatch, [LLDP_NEIGHBOUR, CDP_NEIGHBOUR])

    assert network_info_service.show_cdp_neighbour() == {
        "info": [
            "Name: cisco-sw01",
            "Port: FastEthernet0/8",
            "IP: 192.168.20.1",
            "Native VLAN: 20",
            "Model: cisco WS-C3560-8PC",
        ]
    }


def test_multiple_neighbours_are_labelled_per_interface(monkeypatch):
    second = dict(LLDP_NEIGHBOUR, name="eth1")
    _mock_lldpctl(monkeypatch, [LLDP_NEIGHBOUR, second])

    info = network_info_service.show_lldp_neighbour()["info"]
    assert info[0] == "Interface: eth0"
    assert "Interface: eth1" in info


def test_show_neighbour_reports_empty_table(monkeypatch):
    _mock_lldpctl(monkeypatch, [])

    assert network_info_service.show_lldp_neighbour() == {
        "info": [],
        "error": "No neighbour",
    }


def test_show_neighbour_reports_lldpctl_failure(monkeypatch):
    def fail_run_command(cmd, **kwargs):
        raise RunCommandError("lldpd socket unavailable", 1)

    monkeypatch.setattr(network_info_service, "run_command", fail_run_command)

    assert network_info_service.show_lldp_neighbour() == {
        "info": [],
        "error": "Issue getting LLDP neighbour",
    }


def test_show_neighbour_rejects_non_json_output(monkeypatch):
    monkeypatch.setattr(
        network_info_service,
        "run_command",
        lambda cmd, **kwargs: CommandResult("garbage", "", 0),
    )

    assert network_info_service.show_cdp_neighbour() == {
        "info": [],
        "error": "Issue getting CDP neighbour",
    }


def test_show_vlan_prefers_lldp(monkeypatch):
    _mock_lldpctl(monkeypatch, [LLDP_NEIGHBOUR, CDP_NEIGHBOUR])

    assert network_info_service.show_vlan() == {"info": ["Native VLAN: 102"]}


def test_show_vlan_falls_back_to_cdp(monkeypatch):
    lldp_without_vlan = dict(LLDP_NEIGHBOUR)
    del lldp_without_vlan["vlan"]
    _mock_lldpctl(monkeypatch, [lldp_without_vlan, CDP_NEIGHBOUR])

    assert network_info_service.show_vlan() == {"info": ["Native VLAN: 20"]}


def test_show_vlan_reports_missing_vlan(monkeypatch):
    _mock_lldpctl(monkeypatch, [])

    assert network_info_service.show_vlan() == {
        "info": [],
        "error": "No VLAN found",
    }
