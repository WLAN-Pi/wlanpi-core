"""Tests for P0 network info API additions."""
from unittest.mock import MagicMock, patch

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
