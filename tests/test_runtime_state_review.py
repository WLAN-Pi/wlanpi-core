"""Runtime-state fixes from the review of #285."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from wlanpi_core.schemas.network.network import NetSecurity, RootConfig, SecurityTypes
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService
from wlanpi_core.utils.validation import validate_namespace_name
from wlanpi_core.wpa import supplicant
from wlanpi_core.wpa.config import write_wpa_config

UNIX_PATH_MAX = 107  # sun_path is 108 bytes including the NUL


def test_ctrl_socket_path_fits_for_the_longest_names(monkeypatch):
    monkeypatch.setattr(supplicant, "RUN_DIR", "/run/wlanpi-core")
    namespace = validate_namespace_name("n" * 63)
    socket = Path(supplicant.ctrl_dir(namespace)) / ("i" * 15)
    assert len(str(socket).encode()) <= UNIX_PATH_MAX


def _service(tmp_path) -> NetworkNamespaceService:
    etc = tmp_path / "etc-wpa"
    etc.mkdir()
    return NetworkNamespaceService(config_dir=str(etc), dhcp_dir=str(tmp_path))


def test_remove_network_never_deletes_system_wpa_config(tmp_path):
    service = _service(tmp_path)
    system_conf = service.config_dir / "wpa_supplicant.conf"
    system_conf.write_text("ctrl_interface=/run/wpa_supplicant\n")
    legacy = service.config_dir / "wlan1.conf"
    legacy.write_text("legacy Core config\n")
    with patch.object(service, "_ns_exec"):
        with patch.object(supplicant, "stop_supplicant", return_value=True):
            service.remove_network("wpa_supplicant", None)
            service.remove_network("wlan1", None)
    assert system_conf.exists()
    assert not legacy.exists()


def test_remove_network_removes_the_runtime_log(tmp_path, monkeypatch):
    monkeypatch.setattr(supplicant, "RUN_DIR", str(tmp_path / "run"))
    log = supplicant.log_path("sta0", "ns_a")
    log.parent.mkdir(parents=True)
    log.write_text("wpa log\n")
    service = _service(tmp_path)
    with patch.object(service, "_ns_exec"):
        with patch.object(supplicant, "stop_supplicant", return_value=True):
            service.remove_network("sta0", "ns_a")
    assert not log.exists()


def test_existing_wpa_config_is_made_private(tmp_path):
    path = tmp_path / "wlan1.conf"
    path.write_text("old\n")
    os.chmod(path, 0o644)
    cfg = RootConfig(
        mode="managed",
        iface_display_name="wlan1",
        phy="phy1",
        interface="wlan1",
        security=NetSecurity(ssid="Net", security=SecurityTypes.wpa2, psk="passphrase"),
        default_route=False,
        autostart_app=None,
    )
    write_wpa_config(cfg, path, {}, "/run/wpa_supplicant")
    assert path.stat().st_mode & 0o777 == 0o600


def test_stale_marker_sweep_removes_the_etc_overlay(netcfg_env):
    from wlanpi_core.services import network_namespace_service as nns

    service = netcfg_env["service"]
    marker = Path(nns.RUN_DIR) / "netns" / "gone_ns"
    marker.parent.mkdir(parents=True)
    marker.touch()
    etc = Path(nns.NETNS_ETC_DIR) / "gone_ns"
    etc.mkdir(parents=True)
    (etc / "resolv.conf").write_text("nameserver 192.0.2.1\n")
    # The namespace was deleted out of band.
    with patch.object(nns.ns_namespace, "list_namespaces", return_value=[]):
        assert service.core_namespaces() == []
    assert not marker.exists()
    assert not etc.exists()


def test_reused_namespace_name_starts_with_empty_dns(netcfg_env):
    from tests.conftest import JOSH_THREE_RADIO, live_adapter_inventory_mocks
    from wlanpi_core.schemas.network.network import NamespaceConfig
    from wlanpi_core.services import network_namespace_service as nns

    resolv = Path(nns.NETNS_ETC_DIR) / "ns_a" / "resolv.conf"
    resolv.parent.mkdir(parents=True)
    resolv.write_text("nameserver 192.0.2.1\n")  # left by an earlier ns_a
    cfg = NamespaceConfig(
        namespace="ns_a",
        mode="managed",
        iface_display_name="wlan1",
        phy="phy2",
        interface="wlan1",
        security=None,
        default_route=False,
        autostart_app=None,
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        netcfg_env["service"].activate_config(cfg)
    assert resolv.read_text() == ""


def test_remove_network_keeps_a_foreign_supplicants_socket(tmp_path):
    # #304 review: another supplicant took over the netdev Core used.
    ctrl = tmp_path / "ctrl"
    ctrl.mkdir()
    (ctrl / "wlan1").write_text("")
    service = NetworkNamespaceService(
        config_dir=str(tmp_path), dhcp_dir=str(tmp_path), ctrl_interface=str(ctrl)
    )
    with (
        patch.object(supplicant, "stop_supplicant", return_value=True),
        patch("wlanpi_core.services.network_namespace_service.stop_dhcp"),
        patch(
            "wlanpi_core.adapters.usage.foreign_users",
            return_value=["wpa_supplicant (pid 42)"],
        ),
    ):
        service.remove_network("wlan1", None)
    assert (ctrl / "wlan1").exists()
