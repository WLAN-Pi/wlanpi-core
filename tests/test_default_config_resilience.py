"""Default-config edge cases found reviewing #282 on hardware.

A default that cannot be built, or that would repeat an interface name,
must never stop Core starting.
"""

from unittest.mock import patch

from wlanpi_core.adapters.discovery import LiveInterface
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils import network_config as nc


def test_default_keeps_the_root_entry_when_a_name_repeats(netcfg_env):
    # Linux allows the same netdev name in root and another namespace.
    inventory = [
        LiveInterface("wlan0", 0, None, "managed"),
        LiveInterface("wlan1", 1, None, "managed"),
        LiveInterface("wlan1", 2, "other_ns", "managed"),
    ]
    with (
        patch.object(
            nc.discovery, "list_interfaces_all_namespaces", return_value=inventory
        ),
        # other_ns is Core's, so only the name clash keeps it out
        patch.object(nc.ns, "core_namespaces", return_value=["other_ns"]),
    ):
        cfg = nc.get_default_config()
    assert [(r.interface, r.phy) for r in cfg.roots] == [
        ("wlan0", "phy0"),
        ("wlan1", "phy1"),
    ]


def test_unbuildable_default_is_empty_and_not_written(netcfg_env):
    with patch.object(
        nc.discovery,
        "list_interfaces_all_namespaces",
        side_effect=RunCommandError("iw: command failed", 1),
    ):
        cfg = nc.get_config("default")
    assert cfg.roots == [] and cfg.namespaces == []
    # Nothing persisted, so the next start builds it again.
    assert not (netcfg_env["cfg_dir"] / "default.json").exists()


def test_config_path_stays_inside_the_config_dir(netcfg_env):
    path = nc._config_path("lab_cfg")
    assert path == netcfg_env["cfg_dir"] / "lab_cfg.json"
