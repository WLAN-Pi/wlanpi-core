from wlanpi_core.core import system


def _sync(mocker, layout):
    """Run sync_monitor_interfaces against fake `iw dev` state; return the iw calls."""
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
        return True

    manager = object.__new__(system.SystemManager)
    manager.iface_name = "wlanpi"
    manager.exclusions = []
    mocker.patch.object(manager, "_run", side_effect=fake_run)
    thread = mocker.patch.object(system, "Thread")
    manager.sync_monitor_interfaces()
    added = [cmd[4] for cmd in calls if cmd[2:4] == ["interface", "add"]]
    return added, thread


def test_monitor_named_for_another_phy_is_not_duplicated(mocker):
    added, thread = _sync(mocker, {"wlan0": ("managed", 2), "wlanpi0": ("monitor", 2)})

    assert added == []
    thread.assert_not_called()


def test_missing_monitor_is_created_and_iwlwifi_scans(mocker):
    added, thread = _sync(mocker, {"wlan0": ("managed", 2)})

    assert added == ["wlanpi2"]
    thread.return_value.start.assert_called_once()


def test_no_scan_when_phy_already_has_a_non_core_monitor(mocker):
    added, thread = _sync(mocker, {"wlan0": ("managed", 2), "mon0": ("monitor", 2)})

    assert added == ["wlanpi2"]
    thread.assert_not_called()


def test_one_monitor_per_phy_with_two_managed_interfaces(mocker):
    added, thread = _sync(mocker, {"wlan0": ("managed", 2), "wlan1": ("managed", 2)})

    assert added == ["wlanpi2"]
    thread.return_value.start.assert_called_once()
