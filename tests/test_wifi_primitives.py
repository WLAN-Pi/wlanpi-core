"""Unit tests for Wi-Fi capability and regulatory primitives."""

from unittest.mock import MagicMock, patch

from wlanpi_core.wlan import regulatory


def test_wifi_regulatory_reuses_iw_summary_output():
    summary = {
        "country": "GB",
        "source": "iw",
        "raw": "global\ncountry GB: DFS-ETSI",
    }
    with patch.object(
        regulatory.system_service,
        "get_reg_domain",
        return_value=summary,
    ):
        with patch.object(regulatory, "run_command") as run:
            result = regulatory.get_wifi_regulatory()

    run.assert_not_called()
    assert result == summary


def test_wifi_regulatory_reads_kernel_state_when_summary_uses_script():
    summary = {"country": "GB", "source": "wlanpi-reg-domain", "raw": "GB"}
    with patch.object(
        regulatory.system_service,
        "get_reg_domain",
        return_value=summary,
    ):
        with patch.object(
            regulatory,
            "run_command",
            return_value=MagicMock(stdout="global\ncountry GB: DFS-ETSI\n"),
        ) as run:
            result = regulatory.get_wifi_regulatory()

    run.assert_called_once_with(["iw", "reg", "get"], raise_on_fail=True)
    assert result["source"] == "wlanpi-reg-domain"
    assert result["raw"] == "global\ncountry GB: DFS-ETSI"
