"""Ownership of netdevs Core created (P14)."""

from unittest.mock import patch

import pytest

from wlanpi_core.adapters import discovery
from wlanpi_core.adapters.discovery import LiveInterface


def test_parser_reads_ifindex():
    out = "phy#1\n\tInterface wlan1\n\t\tifindex 7\n\t\ttype managed\n"
    [live] = discovery._parse_iw_dev(out, None)
    assert live == LiveInterface("wlan1", 1, None, "managed", 7)


def test_ownership_lapses_when_someone_else_recreates_the_name(netcfg_env):
    service = netcfg_env["service"]
    ours = LiveInterface("wlan1", 1, None, "managed", 7)
    with patch.object(discovery, "list_interfaces_all_namespaces", return_value=[ours]):
        service._claim("wlan1", None)
    assert service._is_owned(ours)
    # Another tool deleted and recreated wlan1: same name, new ifindex.
    assert not service._is_owned(ours._replace(ifindex=12))


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
