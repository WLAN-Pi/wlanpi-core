"""Ownership of netdevs Core created (P14)."""

from unittest.mock import patch

import pytest

from wlanpi_core.adapters import discovery
from wlanpi_core.adapters.discovery import LiveInterface


def test_parser_reads_ifindex_and_wdev():
    out = (
        "phy#1\n\tInterface wlan1\n\t\tifindex 7\n"
        "\t\twdev 0x100000002\n\t\ttype managed\n"
    )
    [live] = discovery._parse_iw_dev(out, None)
    assert live == LiveInterface("wlan1", 1, None, "managed", 7, "0x100000002")


def test_ownership_lapses_when_someone_else_recreates_the_name(netcfg_env):
    service = netcfg_env["service"]
    ours = LiveInterface("wlan1", 1, None, "managed", 7, "0x100000002")
    with patch.object(discovery, "list_interfaces_all_namespaces", return_value=[ours]):
        service._claim("wlan1", None)
    assert service._is_owned(ours)
    # Another tool deleted and recreated wlan1: same name, new wdev.
    assert not service._is_owned(ours._replace(wdev="0x100000009"))


def test_ownership_survives_a_move_that_changes_the_ifindex(netcfg_env):
    service = netcfg_env["service"]
    in_ns = LiveInterface("wlan1", 1, "ns_a", "monitor", 2, "0x100000002")
    with patch.object(
        discovery, "list_interfaces_all_namespaces", return_value=[in_ns]
    ):
        service._claim("wlan1", "ns_a")
    # Moved home by hand: ifindex 2 was taken in root, the kernel gave 1244.
    home = in_ns._replace(netns=None, ifindex=1244)
    assert service._is_owned(home)
    assert service._owned_path("wlan1", None).exists()
    assert not service._owned_path("wlan1", "ns_a").exists()


def test_failed_marker_write_removes_the_new_namespace(netcfg_env, tmp_path):
    from tests.conftest import JOSH_THREE_RADIO, live_adapter_inventory_mocks
    from tests.test_namespace_matrix.handlers import JOSH_LIVE, _ns, _write_netconfig
    from wlanpi_core.services import network_namespace_service as nns
    from wlanpi_core.utils import network_config as nc

    _write_netconfig(
        netcfg_env,
        "ns_cfg",
        namespaces=[_ns("ns_a", interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    with (
        patch.object(nns, "NETNS_ETC_DIR", str(blocker)),
        live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory,
    ):
        with pytest.raises(OSError):
            nc.activate_config("ns_cfg", override_active=True)
        assert nc.ns.core_namespaces() == []
    assert "ns_a" not in inventory.netns
    assert inventory.live() == JOSH_LIVE
