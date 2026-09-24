"""Unit tests for wpa.scan primitives."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import call, patch

import pytest

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.wpa.scan import (
    MonitorInUseError,
    ScanInProgressError,
    find_bss,
    normalize_scan_detail,
    parse_iw_scan_output,
    parse_key_mgmt,
    parse_wpa_scan_results,
    run_interface_scan,
    run_iw_scan,
)


@pytest.fixture(autouse=True)
def _not_iwlwifi():
    """Default every scan to a non-iwlwifi radio; never read the host sysfs."""
    with patch("wlanpi_core.adapters.discovery.interface_driver", return_value=None):
        yield


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


@pytest.mark.parametrize("freq_text", ["5560", "5560.0"])
def test_parse_iw_scan_output_accepts_int_and_float_freq(freq_text):
    # Older iw prints "freq: 5560", newer prints "freq: 5560.0"; both must
    # parse rather than silently falling back to 0.
    block = f"""\
BSS 00:3e:73:3e:38:32(on wlan0)
\tfreq: {freq_text}
\tsignal: -79.00 dBm
\tSSID: FloatFreq
"""
    networks = parse_iw_scan_output(block)
    assert networks[0]["freq"] == 5560
    assert networks[0]["primaryChannel"] == 112


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
    with patch(
        "wlanpi_core.wpa.scan._interface_is_up", return_value=True
    ) as interface_is_up:
        with patch("wlanpi_core.wpa.scan._set_interface_state") as set_state:
            with patch("wlanpi_core.wpa.scan.wpa_cli_available", return_value=True):
                with patch("wlanpi_core.wpa.scan.run_iw_scan", return_value=[]) as iw:
                    with patch("wlanpi_core.wpa.scan.run_wpa_cli_scan") as wpa:
                        run_interface_scan("wlan0", mode="managed", detail="full")
    interface_is_up.assert_called_once_with("wlan0", None)
    set_state.assert_not_called()
    iw.assert_called_once()
    wpa.assert_not_called()


def test_run_iw_scan_parses_command_output():
    with patch(
        "wlanpi_core.wpa.scan.ns_exec",
        return_value=type(
            "R",
            (),
            {"stdout": SAMPLE_IW, "stderr": "", "return_code": 0},
        )(),
    ):
        networks = run_iw_scan("wlan0")
    assert networks[0]["ssid"] == "TestNet"


def test_interface_state_reads_administrative_up_flag():
    result = type(
        "R",
        (),
        {"stdout": json.dumps([{"flags": ["BROADCAST", "UP", "LOWER_UP"]}])},
    )()
    with patch("wlanpi_core.wpa.scan.ns_exec", return_value=result):
        from wlanpi_core.wpa.scan import _interface_is_up

        assert _interface_is_up("wlan0") is True


def test_run_interface_scan_restores_original_down_state():
    with patch("wlanpi_core.wpa.scan._interface_is_up", return_value=False):
        with patch("wlanpi_core.wpa.scan._set_interface_state") as set_state:
            with patch("wlanpi_core.wpa.scan.run_iw_scan", return_value=[]):
                run_interface_scan("wlan0", mode="monitor")

    assert set_state.call_args_list == [
        call("wlan0", True, None),
        call("wlan0", False, None),
    ]


def test_run_interface_scan_restores_state_after_failure():
    with patch("wlanpi_core.wpa.scan._interface_is_up", return_value=False):
        with patch("wlanpi_core.wpa.scan._set_interface_state") as set_state:
            with patch(
                "wlanpi_core.wpa.scan.run_iw_scan",
                side_effect=RuntimeError("scan failed"),
            ):
                with pytest.raises(RuntimeError, match="scan failed"):
                    run_interface_scan("wlan0", mode="monitor")

    set_state.assert_called_with("wlan0", False, None)


def test_run_interface_scan_rejects_concurrent_target_without_leaking_claim():
    entered = threading.Event()
    release = threading.Event()

    def blocking_scan(*_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=2)
        return []

    with patch("wlanpi_core.wpa.scan._interface_is_up", return_value=True):
        with patch("wlanpi_core.wpa.scan.run_iw_scan", side_effect=blocking_scan):
            with ThreadPoolExecutor(max_workers=1) as executor:
                first = executor.submit(run_interface_scan, "wlan0", mode="monitor")
                assert entered.wait(timeout=2)
                with pytest.raises(ScanInProgressError):
                    run_interface_scan("wlan0", mode="monitor")
                release.set()
                assert first.result(timeout=2) == []

        with patch("wlanpi_core.wpa.scan.run_iw_scan", return_value=[]):
            assert run_interface_scan("wlan0", mode="monitor") == []


SS_WITH_CAPTURE = """\
p_raw UNCONN 0      0           *:wlan0   *
p_dgr UNCONN 0      0      [2054]:eth0    *
p_raw UNCONN 0      0           *:wlanpi1 *
"""


def _iwlwifi(monitors, captured=""):
    """Patch an iwlwifi radio whose `monitors` are up next to wlan0."""
    return (
        patch(
            "wlanpi_core.adapters.discovery.interface_driver", return_value="iwlwifi"
        ),
        patch(
            "wlanpi_core.adapters.phy.up_sibling_monitors", return_value=list(monitors)
        ),
        patch(
            "wlanpi_core.wpa.scan.ns_exec",
            return_value=CommandResult(captured, "", 0),
        ),
    )


def test_iwlwifi_scan_takes_same_radio_monitor_down_and_back_up():
    driver, siblings, ss = _iwlwifi(["wlanpi1"])
    with driver, siblings as sibs, ss:
        with patch("wlanpi_core.wpa.scan._interface_is_up", return_value=False):
            with patch("wlanpi_core.wpa.scan._set_interface_state") as set_state:
                with patch("wlanpi_core.wpa.scan.run_iw_scan", return_value=[]):
                    run_interface_scan("wlan0", "lab_ns", mode="managed", detail="full")

    sibs.assert_called_once_with("wlan0", "lab_ns")
    # Monitor down before the scan radio comes up; back up after it goes down.
    assert set_state.call_args_list == [
        call("wlanpi1", False, "lab_ns"),
        call("wlan0", True, "lab_ns"),
        call("wlan0", False, "lab_ns"),
        call("wlanpi1", True, "lab_ns"),
    ]


def test_non_iwlwifi_scan_leaves_monitors_alone():
    with patch(
        "wlanpi_core.adapters.discovery.interface_driver", return_value="mt7921u"
    ):
        with patch("wlanpi_core.adapters.phy.up_sibling_monitors") as sibs:
            with patch("wlanpi_core.wpa.scan._interface_is_up", return_value=True):
                with patch("wlanpi_core.wpa.scan._set_interface_state") as set_state:
                    with patch("wlanpi_core.wpa.scan.run_iw_scan", return_value=[]):
                        run_interface_scan("wlan1", mode="monitor")
    sibs.assert_not_called()
    set_state.assert_not_called()


def test_iwlwifi_scan_refuses_while_a_capture_holds_the_monitor():
    driver, siblings, ss = _iwlwifi(["wlanpi1"], captured=SS_WITH_CAPTURE)
    with driver, siblings, ss:
        with patch("wlanpi_core.wpa.scan._set_interface_state") as set_state:
            with patch("wlanpi_core.wpa.scan.run_iw_scan") as iw:
                with pytest.raises(MonitorInUseError) as exc:
                    run_interface_scan("wlan0", mode="managed")
                # The claim is released: a later scan is not "in progress".
                with pytest.raises(MonitorInUseError):
                    run_interface_scan("wlan0", mode="managed")

    assert exc.value.code == "MONITOR_IN_USE"
    assert exc.value.monitors == ["wlanpi1"]
    assert isinstance(exc.value, ScanInProgressError)
    set_state.assert_not_called()
    iw.assert_not_called()


def test_iwlwifi_scan_restores_monitor_when_scan_and_teardown_fail():
    driver, siblings, ss = _iwlwifi(["wlanpi1"])

    def set_state(iface, up, _ns):
        if iface == "wlan0" and not up:
            raise RunCommandError("down failed", 1)

    with driver, siblings, ss:
        with patch("wlanpi_core.wpa.scan._interface_is_up", return_value=False):
            with patch(
                "wlanpi_core.wpa.scan._set_interface_state", side_effect=set_state
            ) as state:
                with patch(
                    "wlanpi_core.wpa.scan.run_iw_scan",
                    side_effect=RuntimeError("scan failed"),
                ):
                    with pytest.raises(RunCommandError):
                        run_interface_scan("wlan0", mode="monitor")

    assert state.call_args_list[-1] == call("wlanpi1", True, None)


def test_iwlwifi_scan_restores_every_monitor_when_one_restore_fails():
    driver, siblings, ss = _iwlwifi(["wlanpi1", "wlanpi2"])

    def set_state(iface, up, _ns):
        if iface == "wlanpi1" and up:
            raise OSError("gone")

    with driver, siblings, ss:
        with patch("wlanpi_core.wpa.scan._interface_is_up", return_value=True):
            with patch(
                "wlanpi_core.wpa.scan._set_interface_state", side_effect=set_state
            ) as state:
                with patch("wlanpi_core.wpa.scan.run_iw_scan", return_value=[]):
                    assert run_interface_scan("wlan0", mode="managed") == []

    assert state.call_args_list[-2:] == [
        call("wlanpi1", True, None),
        call("wlanpi2", True, None),
    ]
