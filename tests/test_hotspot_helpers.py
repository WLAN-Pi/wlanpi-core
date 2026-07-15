"""Unit tests for hotspot and wlan helper modules."""
from unittest.mock import patch

import pytest

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import hotspot_service
from wlanpi_core.wlan.stations import _parse_station_blocks


def test_parse_station_blocks():
    output = """Station aa:bb:cc:dd:ee:01 (on wlan0)
\tsignal:  -45 dBm
\ttx bitrate: 72.2 MBit/s
Station bb:cc:dd:ee:ff:00 (on wlan0)
\tsignal:  -60 dBm
"""
    stations = _parse_station_blocks(output)
    assert len(stations) == 2
    assert stations[0]["mac"] == "aa:bb:cc:dd:ee:01"
    assert stations[0]["signal_dbm"] == -45


def test_hotspot_ssid_passphrase_parsing(tmp_path):
    conf = tmp_path / "hostapd.conf"
    conf.write_text("ssid=MySSID\nwpa_passphrase=MyPass\n")
    creds = hotspot_service._parse_hostapd_credentials(conf)
    assert creds == {"ssid": "MySSID", "passphrase": "MyPass"}


def test_hotspot_credentials_report_unreadable_configuration(tmp_path):
    missing = tmp_path / "missing-hostapd.conf"

    with pytest.raises(ValidationError) as exc:
        hotspot_service._parse_hostapd_credentials(missing)

    assert exc.value.status_code == 503
    assert exc.value.error_msg == "Unable to read hostapd configuration"


def test_resolve_ap_interface_explicit():
    status = {"root": {"wlan0": {"type": "ap"}}}
    with patch.object(
        hotspot_service.network_config,
        "status",
        return_value=status,
    ) as read_status:
        assert hotspot_service.resolve_ap_interface("wlan0") == "wlan0"
    read_status.assert_called_once_with()


def test_resolve_ap_interface_rejects_non_ap():
    status = {"root": {"wlan0": {"type": "managed"}}}
    with patch.object(
        hotspot_service.network_config,
        "status",
        return_value=status,
    ) as read_status:
        with pytest.raises(ValidationError):
            hotspot_service.resolve_ap_interface("wlan0")
    read_status.assert_called_once_with()


def test_resolve_ap_interface_reuses_status_for_default_fallback():
    status = {"root": {"wlan0": {"type": "managed"}}}
    with patch.object(
        hotspot_service.network_config,
        "status",
        return_value=status,
    ) as read_status:
        with pytest.raises(ValidationError):
            hotspot_service.resolve_ap_interface()

    read_status.assert_called_once_with()
