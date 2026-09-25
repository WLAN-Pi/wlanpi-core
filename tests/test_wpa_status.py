"""Tests for WPA status parsing and failure handling."""

from unittest.mock import MagicMock

import pytest

from wlanpi_core.wpa import status

_GET_WPA_STATUS = status.get_wpa_status


def test_get_wpa_status_tolerates_non_numeric_frequency(mocker):
    command = mocker.patch.object(
        status,
        "ns_exec",
        side_effect=[
            MagicMock(
                stdout=("ssid=Test Network\nbssid=aa:bb:cc:dd:ee:ff\nfreq=unknown\n")
            ),
            MagicMock(stdout="3: wlan0: <UP>\n"),
        ],
    )
    mocker.patch.object(status, "fetch_scan_results", return_value="")
    mocker.patch.object(status, "parse_wpa_scan_results", return_value=[])

    result = _GET_WPA_STATUS("wlan0", None)

    assert result["connected_scan"]["freq"] == 0
    assert command.call_count == 2


def test_get_wpa_status_matches_mlo_link_by_ssid_and_freq(mocker):
    """On MLO, bssid is the AP MLD address; the association link is found by freq."""
    mocker.patch.object(
        status,
        "ns_exec",
        side_effect=[
            MagicMock(
                stdout=(
                    "bssid=cc:2d:d2:a9:a6:00\nfreq=6375\nssid=676Eval\n"
                    "wpa_state=COMPLETED\nap_mld_addr=cc:2d:d2:a9:a6:00\n"
                )
            ),
            MagicMock(stdout="3: wlan2: <UP>\n"),
        ],
    )
    mocker.patch.object(status, "fetch_scan_results", return_value="")
    mocker.patch.object(
        status,
        "parse_wpa_scan_results",
        return_value=[
            {
                "bssid": "cc:2d:d2:a9:a5:00",
                "ssid": "676Eval",
                "freq": 5660,
                "signal": -41,
            },
            {
                "bssid": "cc:2d:d2:e9:a5:00",
                "ssid": "676Eval",
                "freq": 6375,
                "signal": -45,
                "key_mgmt": "sae",
            },
            {
                "bssid": "aa:bb:cc:dd:ee:ff",
                "ssid": "Other",
                "freq": 6375,
                "signal": -30,
            },
        ],
    )

    result = _GET_WPA_STATUS("wlan2", None)

    assert result["connected_scan"]["signal"] == -45
    assert result["connected_scan"]["key_mgmt"] == "sae"
    assert result["connected_scan"]["bssid"] == "cc:2d:d2:a9:a6:00"


@pytest.mark.parametrize(
    "networks",
    [
        pytest.param(
            [
                {
                    "bssid": "02:00:00:00:00:01",
                    "ssid": "Net",
                    "freq": 5180,
                    "signal": -30,
                    "key_mgmt": "wpa-psk",
                },
                {
                    "bssid": "02:00:00:00:00:02",
                    "ssid": "Net",
                    "freq": 5180,
                    "signal": -60,
                    "key_mgmt": "sae",
                },
            ],
            id="two-aps-same-ssid-and-channel",
        ),
        pytest.param(
            [
                {
                    "bssid": "02:00:00:00:00:01",
                    "ssid": "Net",
                    "freq": 5200,
                    "signal": -30,
                    "key_mgmt": "sae",
                },
                {
                    "bssid": "02:00:00:00:00:02",
                    "ssid": "Other",
                    "freq": 5180,
                    "signal": -30,
                    "key_mgmt": "sae",
                },
            ],
            id="no-ssid-and-freq-match",
        ),
    ],
)
def test_get_wpa_status_mlo_needs_a_unique_link_match(mocker, networks):
    """An ambiguous or missing SSID+freq match reports no signal rather than a guess."""
    mocker.patch.object(
        status,
        "ns_exec",
        side_effect=[
            MagicMock(
                stdout=(
                    "bssid=02:00:00:00:00:aa\nfreq=5180\nssid=Net\n"
                    "ap_mld_addr=02:00:00:00:00:aa\n"
                )
            ),
            MagicMock(stdout="3: wlan0: <UP>\n"),
        ],
    )
    mocker.patch.object(status, "fetch_scan_results", return_value="")
    mocker.patch.object(status, "parse_wpa_scan_results", return_value=networks)

    result = _GET_WPA_STATUS("wlan0", None)

    assert result["connected_scan"]["signal"] == 0
    assert result["connected_scan"]["key_mgmt"] == "unknown"


def test_get_wpa_status_non_mlo_miss_stays_unmatched(mocker):
    """Without ap_mld_addr a BSSID miss is not guessed from SSID and freq."""
    mocker.patch.object(
        status,
        "ns_exec",
        side_effect=[
            MagicMock(stdout="bssid=aa:bb:cc:dd:ee:01\nfreq=5180\nssid=Net\n"),
            MagicMock(stdout="3: wlan0: <UP>\n"),
        ],
    )
    mocker.patch.object(status, "fetch_scan_results", return_value="")
    mocker.patch.object(
        status,
        "parse_wpa_scan_results",
        return_value=[
            {"bssid": "aa:bb:cc:dd:ee:02", "ssid": "Net", "freq": 5180, "signal": -50}
        ],
    )

    result = _GET_WPA_STATUS("wlan0", None)

    assert result["connected_scan"]["signal"] == 0
