"""Unit tests for Wi-Fi capability and regulatory primitives."""

from unittest.mock import MagicMock, patch

from wlanpi_core.models.network.namespace.namespace_errors import (
    NetworkNamespaceError,
)
from wlanpi_core.models.runcommand_error import RunCommandError
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
            with patch.object(capabilities, "list_namespaces", return_value=[]):
                first = capabilities.get_wifi_capabilities()
                second = capabilities.get_wifi_capabilities()

    assert first["adapters"][0]["phy"] == "phy0"
    assert second["adapters"][0]["phy"] == "phy1"
    assert list_phys.call_count == 2


def test_wifi_capabilities_include_phys_in_namespaces():
    """A phy moved into a namespace is listed there, with its namespace (#333)."""

    def fake_list_phys(namespace):
        return {None: ["phy0"], "nsvis": ["phy1"]}[namespace]

    with patch.object(capabilities, "list_phys", side_effect=fake_list_phys):
        with patch.object(capabilities, "list_namespaces", return_value=["nsvis"]):
            with patch.object(
                capabilities, "run_command", return_value=MagicMock(stdout="Wiphy phy0")
            ) as root:
                with patch.object(
                    capabilities, "ns_exec", return_value=MagicMock(stdout="Wiphy phy1")
                ) as in_ns:
                    result = capabilities.get_wifi_capabilities()

    assert result["adapters"] == [
        {"phy": "phy0", "namespace": None, "info": "Wiphy phy0"},
        {"phy": "phy1", "namespace": "nsvis", "info": "Wiphy phy1"},
    ]
    root.assert_called_once()
    assert in_ns.call_args.kwargs["namespace"] == "nsvis"
    assert in_ns.call_args.args[0][1:] == ["phy", "phy1", "info"]


def test_wifi_capabilities_skip_a_failing_namespace():
    def fake_list_phys(namespace):
        if namespace == "broken":
            raise RunCommandError("iw phy failed", 1)
        return ["phy0"]

    with patch.object(capabilities, "list_phys", side_effect=fake_list_phys):
        with patch.object(capabilities, "list_namespaces", return_value=["broken"]):
            with patch.object(
                capabilities, "run_command", return_value=MagicMock(stdout="Wiphy phy0")
            ):
                result = capabilities.get_wifi_capabilities()

    assert [a["phy"] for a in result["adapters"]] == ["phy0"]


def test_wifi_capabilities_root_only_when_namespaces_cannot_be_listed():
    with patch.object(capabilities, "list_phys", return_value=["phy0"]):
        with patch.object(
            capabilities,
            "list_namespaces",
            side_effect=NetworkNamespaceError("ip netns list failed"),
        ):
            with patch.object(
                capabilities, "run_command", return_value=MagicMock(stdout="Wiphy phy0")
            ):
                result = capabilities.get_wifi_capabilities()

    assert result["adapters"] == [
        {"phy": "phy0", "namespace": None, "info": "Wiphy phy0"}
    ]


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
