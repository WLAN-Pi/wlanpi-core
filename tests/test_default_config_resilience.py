"""Default-config edge cases found reviewing #282 on hardware.

A default that cannot be built, or that would repeat an interface name,
must never stop Core starting.
"""

import grp
from unittest.mock import MagicMock, patch

from wlanpi_core import app as app_module
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
    assert not (netcfg_env["cfg_dir"] / "default.json").exists()


def test_config_path_stays_inside_the_config_dir(netcfg_env):
    path = nc._config_path("lab_cfg")
    assert path == netcfg_env["cfg_dir"] / "lab_cfg.json"


async def test_readiness_passes_and_repairs_an_empty_default(netcfg_env, monkeypatch):
    # Old Cortado images shipped a zero-byte default.json.
    cfg_dir = netcfg_env["cfg_dir"]
    (cfg_dir / "default.json").write_text("")
    root = netcfg_env["root"]
    monkeypatch.setattr(app_module, "HOME_DIR", str(root / "home"))
    monkeypatch.setattr(app_module, "SECRETS_DIR", str(root / "data" / "secrets"))
    monkeypatch.setattr(app_module, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(app_module, "CURRENT_CONFIG_FILE", str(netcfg_env["ccf"]))
    monkeypatch.setattr(app_module, "ensure_wlanpi_home_data_dirs", lambda home: None)
    monkeypatch.setattr(
        app_module.grp,
        "getgrnam",
        lambda name: grp.struct_group(("wlanpi", "x", 1000, [])),
    )
    inventory = [LiveInterface("wlan0", 0, None, "managed")]
    manager = app_module.InitializationManager(MagicMock())
    with patch.object(
        nc.discovery, "list_interfaces_all_namespaces", return_value=inventory
    ):
        assert await manager.check_system_readiness() is True
    assert [(r.interface, r.phy) for r in nc.get_config("default").roots] == [
        ("wlan0", "phy0")
    ]
    assert len(list(cfg_dir.glob("default.json.bad-*"))) == 1
