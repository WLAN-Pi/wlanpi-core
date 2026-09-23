"""Unit tests for WLAN scan selection and parsing."""

from unittest.mock import patch

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
    status = {
        "root": {
            "wlanpi0": {"type": "monitor", "wiphy": "0"},
            "wlan0": {"type": "managed", "wiphy": "0"},
        }
    }
    networks = [
        {"ssid": "Test", "bssid": "aa:bb:cc:dd:ee:01", "signal": -50, "freq": 2412}
    ]
    with patch(
        "wlanpi_core.wpa.scan.run_interface_scan", return_value=networks
    ) as run_scan:
        result = wlan_scan(status=status)
    run_scan.assert_called_once_with(
        "wlan0",
        namespace=None,
        include_hidden=True,
        mode="managed",
        detail="short",
    )
    assert result["selectedAdapter"]["iface"] == "wlan0"
    assert result["networks"] == networks
    assert result["detail"] == "short"
    assert result["scannedAt"] is not None


def test_wlan_scan_echoes_detail_and_passes_full():
    status = {"root": {"wlan0": {"type": "managed"}}}
    with patch("wlanpi_core.wpa.scan.run_interface_scan", return_value=[]) as run_scan:
        result = wlan_scan(status=status, detail="full")
    run_scan.assert_called_once_with(
        "wlan0",
        namespace=None,
        include_hidden=True,
        mode="managed",
        detail="full",
    )
    assert result["detail"] == "full"


def test_resolve_scan_target_monitor_delegates_to_managed():
    from wlanpi_core.wlan.scan import resolve_scan_target

    adapters = [
        {
            "iface": "wlanpi0",
            "namespace": None,
            "namespace_display": "root",
            "mode": "monitor",
            "phy": "0",
            "label": "wlanpi0",
        },
        {
            "iface": "wlan0",
            "namespace": None,
            "namespace_display": "root",
            "mode": "managed",
            "phy": "0",
            "label": "wlan0",
        },
    ]
    target = resolve_scan_target(adapters[0], adapters)
    assert target["iface"] == "wlan0"

    # PHY unknown: the monitor scans itself rather than guessing a radio.
    for adapter in adapters:
        adapter["phy"] = None
    assert resolve_scan_target(adapters[0], adapters)["iface"] == "wlanpi0"


# Real `iw dev` from the M4+ in #313: two MediaTek radios and an Intel BE200.
# The PHY appears only in the "phy#N" headers, after TXQ tables.
M4PLUS_IW_DEV = """\
phy#2
\tInterface wlanpi2
\t\tifindex 7
\t\twdev 0x200000002
\t\taddr 94:18:65:3d:69:94
\t\ttype monitor
\t\tchannel 1 (2412 MHz), width: 20 MHz (no HT), center1: 2412 MHz
\tInterface wlan2
\t\tifindex 6
\t\twdev 0x200000001
\t\taddr 94:18:65:3d:69:94
\t\ttype managed
\t\tmulticast TXQ:
\t\t\tqsz-byt\tqsz-pkt\tflows\tdrops\tmarks\toverlmt\thashcol\ttx-bytes\ttx-packets
\t\t\t0\t0\t0\t0\t0\t0\t0\t0\t\t0
phy#0
\tInterface wlanpi0
\t\tifindex 8
\t\twdev 0x2
\t\taddr 9c:ef:d5:f6:b8:69
\t\ttype monitor
\t\tchannel 1 (2412 MHz), width: 20 MHz (no HT), center1: 2412 MHz
\tInterface wlan1
\t\tifindex 4
\t\twdev 0x1
\t\taddr 9c:ef:d5:f6:b8:69
\t\ttype managed
\t\tmulticast TXQ:
\t\t\tqsz-byt\tqsz-pkt\tflows\tdrops\tmarks\toverlmt\thashcol\ttx-bytes\ttx-packets
\t\t\t0\t0\t0\t0\t0\t0\t0\t0\t\t0
phy#1
\tInterface wlanpi1
\t\tifindex 9
\t\twdev 0x100000002
\t\taddr e8:bf:b8:73:9a:47
\t\ttype monitor
\t\tchannel 1 (2412 MHz), width: 20 MHz (no HT), center1: 2412 MHz
\tInterface wlan0
\t\tifindex 3
\t\twdev 0x100000001
\t\taddr e8:bf:b8:73:9a:47
\t\ttype managed
\t\tmulticast TXQ:
\t\t\tqsz-byt\tqsz-pkt\tflows\tdrops\tmarks\toverlmt\thashcol\ttx-bytes\ttx-packets
\t\t\t0\t0\t0\t0\t0\t0\t0\t0\t\t0
"""


@pytest.mark.parametrize(
    ("monitor", "expected"),
    [("wlanpi0", "wlan1"), ("wlanpi1", "wlan0"), ("wlanpi2", "wlan2")],
)
def test_monitor_scan_uses_the_managed_sibling_on_its_own_phy(monitor, expected):
    from wlanpi_core.utils.network_config import parse_iw_dev_output

    status = {"root": parse_iw_dev_output(M4PLUS_IW_DEV)}
    with patch("wlanpi_core.wpa.scan.run_interface_scan", return_value=[]) as run_scan:
        result = wlan_scan(iface=monitor, status=status)
    assert run_scan.call_args.args[0] == expected
    assert result["selectedAdapter"]["iface"] == expected


def test_monitor_scan_never_borrows_another_radio():
    from wlanpi_core.wlan.scan import iter_adapters, resolve_scan_target

    status = {
        "root": {
            "wlanpi1": {"type": "monitor", "wiphy": "1"},
            "wlan2": {"type": "managed", "wiphy": "2"},
        }
    }
    adapters = iter_adapters(status)
    assert resolve_scan_target(adapters[0], adapters)["iface"] == "wlanpi1"


def test_parse_iw_dev_output_records_the_phy_header():
    from wlanpi_core.utils.network_config import parse_iw_dev_output

    parsed = parse_iw_dev_output(M4PLUS_IW_DEV)
    assert {name: info["wiphy"] for name, info in parsed.items()} == {
        "wlanpi2": "2",
        "wlan2": "2",
        "wlanpi0": "0",
        "wlan1": "0",
        "wlanpi1": "1",
        "wlan0": "1",
    }
    assert parsed["wlan2"]["type"] == "managed"
    assert not any(k.startswith("phy#") for info in parsed.values() for k in info)
