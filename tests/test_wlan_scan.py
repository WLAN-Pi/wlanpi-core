"""Unit tests for WLAN scan selection and parsing."""
from unittest.mock import MagicMock, patch

import pytest

from wlanpi_core.wlan.scan import (
    NoScanAdapterError,
    select_scan_adapter,
    wlan_scan,
)
from wlanpi_core.wpa.scan import parse_wpa_scan_results

SAMPLE_SCAN_RESULTS = """\
bssid / frequency / signal level / flags / ssid
aa:bb:cc:dd:ee:01\t2412\t-45\t[WPA2-PSK-CCMP][ESS]\tTestNet
bb:bb:cc:dd:ee:02\t5180\t-60\t[WPA2-PSK-CCMP][ESS]\t
"""


def test_parse_wpa_scan_results_parses_networks():
    networks = parse_wpa_scan_results(SAMPLE_SCAN_RESULTS)
    assert len(networks) == 2
    assert networks[0]["ssid"] == "TestNet"
    assert networks[0]["signal"] == -45
    assert networks[0]["key_mgmt"] == "wpa-psk"


def test_parse_wpa_scan_results_hides_empty_ssid():
    networks = parse_wpa_scan_results(SAMPLE_SCAN_RESULTS, include_hidden=False)
    assert len(networks) == 1
    assert networks[0]["ssid"] == "TestNet"


def test_select_scan_adapter_auto_single_monitor():
    status = {"root": {"wlanpi0": {"type": "monitor"}}}
    result = select_scan_adapter(status)
    assert result["action"] == "scan"
    assert result["adapter"]["iface"] == "wlanpi0"


def test_select_scan_adapter_needs_selection_for_two_monitors():
    status = {
        "root": {
            "wlanpi0": {"type": "monitor"},
            "wlanpi1": {"type": "monitor"},
        }
    }
    result = select_scan_adapter(status)
    assert result["action"] == "needs_selection"
    assert len(result["candidates"]) == 2


def test_select_scan_adapter_managed_root_fallback():
    status = {"root": {"wlan0": {"type": "managed"}}}
    result = select_scan_adapter(status)
    assert result["action"] == "scan"
    assert result["adapter"]["iface"] == "wlan0"


def test_select_scan_adapter_explicit_iface_and_namespace():
    status = {
        "root": {"wlanpi0": {"type": "monitor"}},
        "scan_ns": {"wlanpi1": {"type": "monitor"}},
    }
    result = select_scan_adapter(status, iface="wlanpi1", namespace="scan_ns")
    assert result["action"] == "scan"
    assert result["adapter"]["namespace"] == "scan_ns"


def test_select_scan_adapter_raises_when_no_adapter():
    status = {"root": {}}
    with pytest.raises(NoScanAdapterError):
        select_scan_adapter(status)


def test_wlan_scan_returns_needs_selection_without_scanning():
    status = {
        "root": {
            "wlanpi0": {"type": "monitor"},
            "wlanpi1": {"type": "monitor"},
        }
    }
    with patch("wlanpi_core.wpa.scan.run_interface_scan") as run_scan:
        result = wlan_scan(status=status)
    run_scan.assert_not_called()
    assert result["needsSelection"] is True
    assert len(result["candidates"]) == 2


def test_wlan_scan_runs_scan_for_single_monitor():
    status = {"root": {"wlanpi0": {"type": "monitor"}}}
    networks = [{"ssid": "Test", "bssid": "aa:bb:cc:dd:ee:01", "signal": -50, "freq": 2412}]
    with patch("wlanpi_core.wpa.scan.run_interface_scan", return_value=networks):
        result = wlan_scan(status=status)
    assert result["selectedAdapter"]["iface"] == "wlanpi0"
    assert result["networks"] == networks
    assert result["scannedAt"] is not None
