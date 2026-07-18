"""Tests for WPA status parsing and failure handling."""

from unittest.mock import MagicMock

from wlanpi_core.wpa import status

_GET_WPA_STATUS = status.get_wpa_status


def test_get_wpa_status_tolerates_non_numeric_frequency(mocker):
    command = mocker.patch.object(
        status,
        "ns_exec",
        side_effect=[
            MagicMock(
                stdout=(
                    "ssid=Test Network\n"
                    "bssid=aa:bb:cc:dd:ee:ff\n"
                    "freq=unknown\n"
                )
            ),
            MagicMock(stdout="3: wlan0: <UP>\n"),
        ],
    )
    mocker.patch.object(status, "fetch_scan_results", return_value="")
    mocker.patch.object(status, "parse_wpa_scan_results", return_value=[])

    result = _GET_WPA_STATUS("wlan0", None)

    assert result["connected_scan"]["freq"] == 0
    assert command.call_count == 2
