"""Unit tests for wpa.scan primitives."""
from wlanpi_core.wpa.scan import find_bss, parse_key_mgmt, parse_wpa_scan_results

SAMPLE = """\
bssid / frequency / signal level / flags / ssid
aa:bb:cc:dd:ee:01\t2412\t-45\t[WPA2-PSK-CCMP][ESS]\tTestNet
"""


def test_parse_key_mgmt_wpa2_psk():
    assert parse_key_mgmt("[WPA2-PSK-CCMP][ESS]") == "wpa-psk"


def test_find_bss_matches_lowercase():
    networks = parse_wpa_scan_results(SAMPLE)
    matched = find_bss(networks, "AA:BB:CC:DD:EE:01")
    assert matched is not None
    assert matched["ssid"] == "TestNet"
