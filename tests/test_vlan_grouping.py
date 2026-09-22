"""Tests for live VLAN grouping and the legacy-file-free service path."""

from unittest.mock import MagicMock, patch

import pytest

from wlanpi_core.models.network.vlan import LiveVLANs
from wlanpi_core.schemas.network.network import IPInterface
from wlanpi_core.services import network_ethernet_service

_GET_INTERFACES = "wlanpi_core.models.network.vlan.live.common.get_interfaces"


def _vlan_interface(ifname: str = "eth0.50", **extra) -> IPInterface:
    data = {
        "ifindex": 4,
        "ifname": ifname,
        "flags": ["BROADCAST", "MULTICAST", "UP"],
        "mtu": 1500,
        "qdisc": "noqueue",
        "operstate": "UP",
        "group": "default",
        "txqlen": 1000,
        "link_type": "ether",
        "address": "d8:3a:dd:96:a5:73",
        "broadcast": "ff:ff:ff:ff:ff:ff",
        "addr_info": [],
        **extra,
    }
    return IPInterface.model_validate(data)


def test_vlan_grouped_by_parent_from_link_field():
    vlan = _vlan_interface(link="eth0")

    with patch(_GET_INTERFACES, return_value=[vlan]):
        grouped = LiveVLANs.get_vlan_interfaces_by_interface()

    assert grouped == {"eth0": [vlan]}


def test_vlan_grouped_by_parent_name_fallback():
    vlan = _vlan_interface()

    with patch(_GET_INTERFACES, return_value=[vlan]):
        grouped = LiveVLANs.get_vlan_interfaces_by_interface()

    assert grouped == {"eth0": [vlan]}


@pytest.mark.asyncio
async def test_get_vlans_returns_vlan_under_parent():
    vlan = _vlan_interface(link="eth0")

    with patch(_GET_INTERFACES, return_value=[vlan]):
        result = await network_ethernet_service.get_vlans(interface="eth0")

    assert result == {"eth0": [vlan]}


@pytest.mark.asyncio
async def test_remove_vlan_does_not_need_legacy_file():
    delete_vlan = MagicMock()

    with patch.object(LiveVLANs, "delete_vlan", delete_vlan):
        await network_ethernet_service.remove_vlan("eth0", 50, allow_missing=True)

    delete_vlan.assert_called_once_with(if_name="eth0", vlan_id=50, allow_missing=True)
