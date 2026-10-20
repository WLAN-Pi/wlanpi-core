"""Profile write and delete fixes from the review of #290."""

import pytest

from wlanpi_core.models.network_config_errors import ConfigBusyError
from wlanpi_core.schemas.network.network import NetConfig
from wlanpi_core.utils import network_config as nc


def test_current_txt_stays_world_readable(netcfg_env):
    nc._write_current("default")
    assert netcfg_env["ccf"].stat().st_mode & 0o777 == 0o644


def test_profiles_are_private(netcfg_env):
    nc.add_config(NetConfig(id="lab_cfg", namespaces=[], roots=[]))
    path = netcfg_env["cfg_dir"] / "lab_cfg.json"
    assert path.stat().st_mode & 0o777 == 0o600


def test_delete_waits_for_no_other_change(netcfg_env):
    nc.add_config(NetConfig(id="lab_cfg", namespaces=[], roots=[]))
    with nc.network_change_lock():
        with pytest.raises(ConfigBusyError):
            nc.delete_config("lab_cfg")
    assert (netcfg_env["cfg_dir"] / "lab_cfg.json").exists()
