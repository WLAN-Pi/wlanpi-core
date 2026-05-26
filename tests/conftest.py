"""Shared fixtures for namespace matrix tests."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from wlanpi_core.connection.monitor import ConnectionMonitor
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService

_REAL_CONNECTION_MONITOR_START = ConnectionMonitor.start_monitor


@pytest.fixture(autouse=True)
def _clean_connection_monitors():
    from wlanpi_core.connection.monitor import stop_all_connection_monitors

    stop_all_connection_monitors()
    yield
    stop_all_connection_monitors()
    if ConnectionMonitor.start_monitor is not _REAL_CONNECTION_MONITOR_START:
        ConnectionMonitor.start_monitor = _REAL_CONNECTION_MONITOR_START


@pytest.fixture
def netcfg_env(tmp_path, monkeypatch):
    """Isolated config directory and current.txt for network_config module."""
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    ccf = tmp_path / "current.txt"
    ccf.write_text("default")

    monkeypatch.setattr("wlanpi_core.utils.network_config.cfg_dir", cfg_dir)
    monkeypatch.setattr("wlanpi_core.utils.network_config.ccf", ccf)

    service = NetworkNamespaceService(
        config_dir=tmp_path / "wpa",
        dhcp_dir=tmp_path / "dhcp",
    )
    service.config_dir.mkdir(parents=True, exist_ok=True)
    service.dhcp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("wlanpi_core.utils.network_config.ns", service)

    return {"cfg_dir": cfg_dir, "ccf": ccf, "service": service, "root": tmp_path}


@pytest.fixture
def namespace_service(netcfg_env):
    return netcfg_env["service"]


@contextmanager
def hardware_success_mocks(interfaces=None, phy_move_side_effect=None):
    """Mock adapter/namespace stack so activate/deactivate paths succeed in CI."""
    interfaces = interfaces or ["wlan0", "wlan1"]

    def _move_phy(phy_name, namespace):
        if phy_move_side_effect is not None:
            result = phy_move_side_effect(phy_name, namespace)
            if result is RunCommandError or isinstance(result, Exception):
                raise result
            if result is False:
                raise RunCommandError("phy move failed", 1)
        return None

    patches = [
        patch(
            "wlanpi_core.services.network_namespace_service.discovery.list_interfaces",
            return_value=interfaces,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.namespace_exists",
            return_value=False,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.create_namespace",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.list_namespaces",
            return_value=[],
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.delete_namespace",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.interface.delete_interface",
            side_effect=RunCommandError("No such device", 1),
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.interface.create_interface",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.interface.bring_interface_up",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.phy.list_phys",
            return_value=[],
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.phy.move_phy_to_namespace",
            side_effect=_move_phy,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.phy.move_phy_to_root",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.wpa_config.write_wpa_config",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.write_dhcp_config",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.wpa_supplicant.start_or_restart_supplicant",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.wpa_supplicant.kill_all_supplicants",
        ),
        patch.object(
            NetworkNamespaceService,
            "_monitor_connection_async",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.apps.start_app_in_namespace",
            return_value=True,
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.apps.stop_app_in_namespace",
        ),
        patch(
            "wlanpi_core.services.network_namespace_service.run_command",
            return_value=CommandResult(stdout="phy0\nphy1", stderr="", return_code=0),
        ),
    ]

    started = [p.start() for p in patches]
    try:
        yield
    finally:
        for p in reversed(started):
            p.stop()


def write_json_config(cfg_dir: Path, cfg_id: str, payload: dict) -> Path:
    path = cfg_dir / f"{cfg_id}.json"
    import json

    path.write_text(json.dumps(payload, indent=4))
    return path
