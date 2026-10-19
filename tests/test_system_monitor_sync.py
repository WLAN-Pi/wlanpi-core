import pytest

from wlanpi_core.core import system

# Trimmed `iw phy <phy> info` output from a WLAN Pi R4 (#348).
MT7921_PHY_INFO = """Wiphy phy0
\twiphy index: 0
\tSupported interface modes:
\t\t * managed
\t\t * AP
\t\t * AP/VLAN
\t\t * monitor
\t\t * P2P-client
\t\t * P2P-GO
\t\t * P2P-device
\tBand 1:
\tsoftware interface modes (can always be added):
\t\t * AP/VLAN
\t\t * monitor
\tvalid interface combinations:
"""

BRCMFMAC_PHY_INFO = """Wiphy phy2
\twiphy index: 2
\tSupported interface modes:
\t\t * IBSS
\t\t * managed
\t\t * AP
\t\t * P2P-client
\t\t * P2P-GO
\t\t * P2P-device
\tBand 1:
\tsoftware interface modes (can always be added):
\tvalid interface combinations:
\t\t * managed: 0x00 0x10 0x20 0x30 0x40 0x50 0x60 0x70 0x80 0x90 0xa0 0xb0
"""


def _sync(mocker, layout, no_monitor=()):
    """Run sync_monitor_interfaces against fake `iw dev` state."""
    iw_dev = "".join(
        f"phy#{phy}\n\tInterface {name}\n\t\ttype {typ}\n"
        for name, (typ, phy) in layout.items()
    )
    calls = []

    def fake_run(cmd, capture_output=False, suppress_output=False):
        calls.append(cmd)
        if cmd[1:] == ["dev"]:
            return iw_dev
        if cmd[1] == "dev" and cmd[3:] == ["info"]:
            return f"Interface {cmd[2]}\n\twiphy {layout[cmd[2]][1]}\n"
        if cmd[1:2] == ["-i"]:
            return "driver: iwlwifi\nversion: 7.3.0\n"
        if cmd[1] == "phy" and cmd[3:] == ["info"]:
            phy = int(cmd[2].removeprefix("phy"))
            return BRCMFMAC_PHY_INFO if phy in no_monitor else MT7921_PHY_INFO
        return True

    manager = object.__new__(system.SystemManager)
    manager.iface_name = "wlanpi"
    manager.exclusions = []
    mocker.patch.object(manager, "_run", side_effect=fake_run)
    thread = mocker.patch.object(system, "Thread")
    manager.sync_monitor_interfaces()
    added = [cmd[4] for cmd in calls if cmd[2:4] == ["interface", "add"]]
    downs = [
        cmd[3] for cmd in calls if cmd[1:3] == ["link", "set"] and cmd[4:] == ["down"]
    ]
    return added, thread, downs


def test_monitor_named_for_another_phy_is_not_duplicated(mocker):
    added, thread, _ = _sync(
        mocker, {"wlan0": ("managed", 2), "wlanpi0": ("monitor", 2)}
    )

    assert added == []
    thread.assert_not_called()


def test_missing_monitor_is_created_and_iwlwifi_scans(mocker):
    added, thread, _ = _sync(mocker, {"wlan0": ("managed", 2)})

    assert added == ["wlanpi2"]
    thread.return_value.start.assert_called_once()


def test_no_scan_when_phy_already_has_a_non_core_monitor(mocker):
    added, thread, downs = _sync(
        mocker, {"wlan0": ("managed", 2), "mon0": ("monitor", 2)}
    )

    assert added == ["wlanpi2"]
    thread.assert_not_called()
    assert downs == ["wlan0"]


def test_one_monitor_per_phy_with_two_managed_interfaces(mocker):
    added, thread, _ = _sync(mocker, {"wlan0": ("managed", 2), "wlan1": ("managed", 2)})

    assert added == ["wlanpi2"]
    thread.return_value.start.assert_called_once()


def test_phy_without_monitor_mode_is_skipped(mocker):
    added, thread, downs = _sync(mocker, {"wlan0": ("managed", 2)}, no_monitor={2})

    assert added == []
    thread.assert_not_called()
    assert downs == []


def test_other_phys_still_get_monitors_when_one_has_no_monitor_mode(mocker):
    added, _, _ = _sync(
        mocker,
        {"wlan0": ("managed", 2), "wlan1": ("managed", 0), "wlan2": ("managed", 1)},
        no_monitor={2},
    )

    assert added == ["wlanpi0", "wlanpi1"]


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (MT7921_PHY_INFO, True),
        (BRCMFMAC_PHY_INFO, False),
        ("\tsoftware interface modes (can always be added):\n\t\t * monitor\n", True),
        ("Wiphy phy9\n\twiphy index: 9\n", True),
        (None, True),
    ],
    ids=["mt7921", "brcmfmac", "software-modes-only", "no-mode-list", "no-output"],
)
def test_supports_monitor_reads_iw_phy_interface_modes(mocker, output, expected):
    manager = object.__new__(system.SystemManager)
    mocker.patch.object(manager, "_run", return_value=output)

    assert manager._supports_monitor("2") is expected
