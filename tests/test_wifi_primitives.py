"""Unit tests for Wi-Fi capability and regulatory primitives."""

from unittest.mock import MagicMock, patch

from wlanpi_core.wlan import capabilities, regulatory


def test_wifi_capabilities_are_not_cached():
    with patch.object(
        capabilities,
        "list_phys",
        side_effect=[["phy0"], ["phy1"]],
    ) as list_phys:
        with patch.object(
            capabilities,
            "run_command",
            side_effect=[
                MagicMock(stdout="Wiphy phy0"),
                MagicMock(stdout="Wiphy phy1"),
            ],
        ):
            first = capabilities.get_wifi_capabilities()
            second = capabilities.get_wifi_capabilities()

    assert first["adapters"][0]["phy"] == "phy0"
    assert second["adapters"][0]["phy"] == "phy1"
    assert list_phys.call_count == 2


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
