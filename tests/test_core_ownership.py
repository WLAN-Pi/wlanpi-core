"""Ownership of netdevs Core created (P14)."""

from unittest.mock import patch

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
