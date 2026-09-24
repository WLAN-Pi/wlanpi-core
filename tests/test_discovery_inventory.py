"""Inventory edge cases seen on WLAN Pi hardware (review of #281).

Tests by Josh Schmelzle, from his review of the namespace safety series.
"""

from unittest.mock import patch

import pytest

from wlanpi_core.adapters import discovery
from wlanpi_core.models.command_result import CommandResult

# iw 6.17 on mt7921u/iwlwifi once wpa_supplicant has run: the P2P-device
# wdev has a type line but no netdev.
IW_DEV_WITH_P2P_WDEV = """phy#0
\tInterface wlanpi0
\t\tifindex 6
\t\ttype monitor
phy#1
\tUnnamed/non-netdev interface
\t\twdev 0x100000002
\t\ttype P2P-device
\tInterface wlan1
\t\tifindex 5
\t\ttype managed
"""


def test_parse_iw_dev_unnamed_wdev_does_not_retype_previous_netdev():
    parsed = discovery._parse_iw_dev(IW_DEV_WITH_P2P_WDEV, None)
    assert [(e.name, e.phy_index, e.type) for e in parsed] == [
        ("wlanpi0", 0, "monitor"),
        ("wlan1", 1, "managed"),
    ]


def test_inventory_skips_netns_with_name_core_refuses():
    root = CommandResult(
        stdout="phy#0\n\tInterface wlan0\n\t\ttype managed\n", stderr="", return_code=0
    )
    with (
        patch("wlanpi_core.adapters.discovery.run_command", return_value=root),
        patch(
            "wlanpi_core.namespaces.namespace.list_namespaces", return_value=["lab:1"]
        ),
        # ns_exec's own run_command: must never run for a refused name
        patch(
            "wlanpi_core.utils.namespace_execution.run_command",
            side_effect=AssertionError("ns_exec ran a command for an invalid netns"),
        ) as ns_run,
    ):
        found = discovery.list_interfaces_all_namespaces()
    assert [(e.name, e.netns) for e in found] == [("wlan0", None)]
    ns_run.assert_not_called()


@pytest.mark.parametrize(
    ("stdout", "rc", "driver"),
    [
        ("/sys/bus/pci/drivers/iwlwifi\n", 0, "iwlwifi"),
        ("/sys/bus/usb/drivers/mt7921u\n", 0, "mt7921u"),
        ("", 1, None),  # no such netdev in that namespace
    ],
)
def test_interface_driver_reads_sysfs_in_the_namespace(stdout, rc, driver):
    with patch(
        "wlanpi_core.adapters.discovery.ns_exec",
        return_value=CommandResult(stdout, "", rc),
    ) as ns_exec:
        assert discovery.interface_driver("wlan0", "lab_ns") == driver
    ns_exec.assert_called_once_with(
        ["readlink", "-f", "/sys/class/net/wlan0/device/driver"],
        namespace="lab_ns",
        no_output=True,
        raise_on_fail=False,
    )


IW_DEV_TWO_RADIOS = """phy#1
\tInterface wlanpi1
\t\ttype monitor
\tInterface wlan0
\t\ttype managed
phy#0
\tInterface wlanpi0
\t\ttype monitor
\tInterface wlan1
\t\ttype managed
"""


def test_up_sibling_monitors_only_returns_the_same_radio():
    from wlanpi_core.adapters import phy

    def ns_exec(cmd, namespace=None, **_kw):
        if cmd[-1] == "dev":
            return CommandResult(IW_DEV_TWO_RADIOS, "", 0)
        # `ip -o link show up`: both monitors are up.
        return CommandResult(
            "7: wlanpi1: <UP> mtu 1500\n6: wlanpi0: <UP> mtu 1500\n", "", 0
        )

    with patch("wlanpi_core.adapters.phy.ns_exec", side_effect=ns_exec):
        assert phy.up_sibling_monitors("wlan0", None) == ["wlanpi1"]
        assert phy.up_sibling_monitors("wlan1", None) == ["wlanpi0"]
        assert phy.up_sibling_monitors("wlanpi1", None) == []  # not itself
        assert phy.up_sibling_monitors("wlan9", None) == []  # unknown iface
