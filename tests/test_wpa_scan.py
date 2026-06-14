"""Unit tests for wpa.scan primitives."""
from unittest.mock import patch

import pytest

from wlanpi_core.wpa.scan import (
    find_bss,
    normalize_scan_detail,
    parse_iw_scan_output,
    parse_key_mgmt,
    parse_wpa_scan_results,
    run_iw_scan,
    run_interface_scan,
)

SAMPLE = """\
bssid / frequency / signal level / flags / ssid
aa:bb:cc:dd:ee:01\t2412\t-45\t[WPA2-PSK-CCMP][ESS]\tTestNet
"""

SAMPLE_IW = """\
BSS d8:b3:70:dc:4d:f9(on wlan0)
\tlast seen: 1465.186s [boottime]
\tsignal: -52.00 dBm
\tSSID: TestNet
\tfreq: 5180
\tcapability: ESS Privacy ShortSlotTime (0x0411)
\tRSN: * Version: 1
\tHT capabilities:
\tHT operation:
\t\t * primary channel: 36
\t\t * secondary channel offset: above control channel
\tVHT operation:
\t\t * channel width: 80 MHz
\tBSS Load Element:
\t\t * station count: 4
\t\t * channel utilisation: 32/255
"""

SAMPLE_IW_FULL_BLOCK = SAMPLE_IW.strip()


def test_parse_key_mgmt_wpa2_psk():
    assert parse_key_mgmt("[WPA2-PSK-CCMP][ESS]") == "wpa-psk"


def test_find_bss_matches_lowercase():
    networks = parse_wpa_scan_results(SAMPLE)
    matched = find_bss(networks, "AA:BB:CC:DD:EE:01")
    assert matched is not None
    assert matched["ssid"] == "TestNet"


def test_parse_iw_scan_output_parses_bss():
    networks = parse_iw_scan_output(SAMPLE_IW)
    assert len(networks) == 1
    assert networks[0]["bssid"] == "d8:b3:70:dc:4d:f9"
    assert networks[0]["ssid"] == "TestNet"
    assert networks[0]["signal"] == -52
    assert networks[0]["freq"] == 5180
    assert networks[0]["key_mgmt"] == "wpa-psk"
    assert networks[0]["primaryChannel"] == 36
    assert networks[0]["channelWidth"] == 80
    assert networks[0]["secondaryChannelOffset"] == "above"
    assert networks[0]["bssLoad"]["stations"] == 4
    assert networks[0]["bssLoad"]["utilization"] == 32
    assert "n" in networks[0]["amendments"]
    assert "ac" in networks[0]["amendments"]
    assert "raw" not in networks[0]


def test_parse_iw_scan_output_full_includes_raw():
    networks = parse_iw_scan_output(SAMPLE_IW, detail="full")
    assert networks[0]["raw"] == SAMPLE_IW_FULL_BLOCK


def test_parse_secondary_channel_offset_values():
    above = parse_iw_scan_output(SAMPLE_IW)[0]["secondaryChannelOffset"]
    assert above == "above"

    no_secondary = """\
BSS aa:bb:cc:dd:ee:02(on wlan0)
\tsignal: -60.00 dBm
\tSSID: Solo20
\tfreq: 2412
\tHT operation:
\t\t * primary channel: 1
\t\t * secondary channel offset: no secondary
"""
    assert parse_iw_scan_output(no_secondary)[0]["secondaryChannelOffset"] == "none"


def test_parse_wpa_scan_results_includes_flags():
    networks = parse_wpa_scan_results(SAMPLE)
    assert networks[0]["flags"] == "[WPA2-PSK-CCMP][ESS]"
    assert networks[0]["primaryChannel"] == 1
    assert networks[0]["secondaryChannelOffset"] is None


def test_normalize_scan_detail_accepts_short_and_full():
    assert normalize_scan_detail("short") == "short"
    assert normalize_scan_detail("FULL") == "full"


def test_normalize_scan_detail_rejects_invalid():
    with pytest.raises(ValueError, match="detail must be one of"):
        normalize_scan_detail("verbose")


def test_run_interface_scan_full_prefers_iw_over_wpa_cli():
    with patch("wlanpi_core.wpa.scan.ensure_iface_up"):
        with patch("wlanpi_core.wpa.scan.wpa_cli_available", return_value=True):
            with patch("wlanpi_core.wpa.scan.run_iw_scan", return_value=[]) as iw:
                with patch("wlanpi_core.wpa.scan.run_wpa_cli_scan") as wpa:
                    run_interface_scan("wlan0", mode="managed", detail="full")
    iw.assert_called_once()
    wpa.assert_not_called()


def test_run_iw_scan_brings_iface_up():
    with patch("wlanpi_core.wpa.scan.ensure_iface_up") as up:
        with patch(
            "wlanpi_core.wpa.scan.ns_exec",
            return_value=type(
                "R",
                (),
                {"stdout": SAMPLE_IW, "stderr": "", "return_code": 0},
            )(),
        ):
            networks = run_iw_scan("wlan0")
    up.assert_called_once_with("wlan0", None)
    assert networks[0]["ssid"] == "TestNet"
