"""Inventory edge cases seen on WLAN Pi hardware (review of #281).

Tests by Josh Schmelzle, from his review of the namespace safety series.
"""

from unittest.mock import patch

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
