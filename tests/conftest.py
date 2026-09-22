"""Shared fixtures for namespace matrix tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wlanpi_core.connection.monitor import ConnectionMonitor
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService

_REAL_CONNECTION_MONITOR_START = ConnectionMonitor.start_monitor


@pytest.fixture(scope="session", autouse=True)
def mock_wlanpi_group():
    """Prevent startup readiness failures when the wlanpi group is absent in CI."""
    mock_group = MagicMock()
    mock_group.gr_gid = 1000
    mock_group.gr_name = "wlanpi"

    with patch("grp.getgrnam", return_value=mock_group):
        yield


@pytest.fixture(autouse=True)
def mock_app_initialization(monkeypatch):
    """Bypass filesystem-dependent startup in CI and local pytest."""

    async def _mock_initialize_components(self):
        self.initialized = True
        return True

    monkeypatch.setattr(
        "wlanpi_core.app.InitializationManager.initialize_components",
        _mock_initialize_components,
    )
    monkeypatch.setattr(
        "wlanpi_core.services.system_service.get_mode",
        lambda: "classic",
    )


_DEFAULT_WPA_STATUS = {
    "wpa_status": {
        "wpa_state": "COMPLETED",
        "ssid": "test",
        "bssid": "00:11:22:33:44:55",
    },
    "ip_info": "",
    "connected_scan": {
        "ssid": "test",
        "bssid": "00:11:22:33:44:55",
        "key_mgmt": "open",
        "freq": 2412,
        "signal": 0,
        "minrate": 1000000,
    },
}


def _mock_namespace_run_command(cmd, raise_on_fail=True, **kwargs):
    """Avoid real sudo/ip netns/wpa_cli execution in CI and local pytest."""
    joined = " ".join(str(part) for part in cmd)
    if "wpa_cli" in joined and "status" in joined:
        stdout = "wpa_state=COMPLETED\nssid=test\nbssid=00:11:22:33:44:55\n"
    elif "wpa_cli" in joined and "scan_results" in joined:
        stdout = "bssid / frequency / signal level / flags / ssid\n"
    elif " iw " in f" {joined} " and " phy" in joined:
        stdout = "phy0\nphy1\n"
    else:
        stdout = ""
    return CommandResult(stdout=stdout, stderr="", return_code=0)


@pytest.fixture
def mock_namespace_execution():
    """Block all namespace command execution during tests."""
    patches = [
        patch(
            "wlanpi_core.utils.namespace_execution.run_command",
            side_effect=_mock_namespace_run_command,
        ),
        patch(
            "wlanpi_core.wpa.status.get_wpa_status",
            return_value=_DEFAULT_WPA_STATUS.copy(),
        ),
        patch.object(
            NetworkNamespaceService,
            "get_status",
            return_value=_DEFAULT_WPA_STATUS.copy(),
        ),
    ]
    started = [p.start() for p in patches]
    try:
        yield
    finally:
        for p in reversed(started):
            p.stop()


@pytest.fixture(autouse=True)
def _isolate_namespace_execution(mock_namespace_execution):
    """Ensure matrix and service tests never invoke real netns commands."""
    yield mock_namespace_execution


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


@dataclass
class InventoryRecorder:
    """Live iface→phy→MAC map plus recorded prepare mutations."""

    adapters: dict[str, dict[str, str]]
    deleted: list[tuple[str, str | None]] = field(default_factory=list)
    adds: list[tuple[str, str]] = field(default_factory=list)
    phy_moves: list[tuple[str, str]] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)

    def phys(self) -> list[str]:
        return sorted({meta["phy"] for meta in self.adapters.values()})

    def added_phy(self, iface: str) -> str | None:
        matches = [phy for phy, name in self.adds if name == iface]
        return matches[-1] if matches else None

    def last_moved_phy(self) -> str | None:
        return self.phy_moves[-1][0] if self.phy_moves else None


# Josh's 3-radio boot (#236): BE200 phy0/wlan0, mt7921u phy1/wlan2, MT7612U phy2/wlan1.
JOSH_THREE_RADIO: dict[str, dict[str, str]] = {
    "wlan0": {"phy": "phy0", "mac": "00:11:22:33:44:00"},
    "wlan1": {"phy": "phy2", "mac": "00:11:22:33:44:01"},
    "wlan2": {"phy": "phy1", "mac": "00:11:22:33:44:02"},
}


@contextmanager
def live_adapter_inventory_mocks(adapters: dict[str, dict[str, str]] | None = None):
    """Stub a live iface/phy/MAC inventory and record delete, add, and phy move.

    Unlike hardware_success_mocks, this exposes which PHY received
    `iw phy <phy> interface add <iface>` so identity-mismatch rows can assert
    the mapping instead of only `activate_config is True`.
    """
    adapters = adapters or dict(JOSH_THREE_RADIO)
    recorder = InventoryRecorder(adapters=adapters)

    def _move_phy(phy_name: str, namespace: str) -> None:
        recorder.phy_moves.append((phy_name, namespace))
        if phy_name not in recorder.phys():
            raise RunCommandError(f"{phy_name} does not exist", 1)
        return None

    def _delete(iface: str, namespace: str | None = None) -> None:
        recorder.deleted.append((iface, namespace))
        return None

    def _run_command(
        cmd: list[str], raise_on_fail: bool = True, **kwargs: Any
    ) -> CommandResult:
        parts = [str(item) for item in cmd]
        recorder.commands.append(parts)
        joined = parts[1:] if parts and parts[0] == "sudo" else parts

        if joined == ["iw", "phy"]:
            stdout = "\n".join(f"Wiphy {phy}" for phy in recorder.phys()) + "\n"
            return CommandResult(stdout=stdout, stderr="", return_code=0)

        if (
            len(joined) >= 6
            and joined[0:2] == ["iw", "phy"]
            and joined[3:5] == ["interface", "add"]
        ):
            recorder.adds.append((joined[2], joined[5]))
            return CommandResult(stdout="", stderr="", return_code=0)

        if "set" in joined and "netns" in joined:
            try:
                phy_name = joined[joined.index("phy") + 1]
            except (ValueError, IndexError):
                phy_name = ""
            if phy_name not in recorder.phys():
                raise RunCommandError(f"{phy_name} does not exist", 1)
            return CommandResult(stdout="", stderr="", return_code=0)

        if len(joined) >= 4 and joined[0:2] == ["iw", "dev"] and joined[-1] == "info":
            iface = joined[2]
            meta = recorder.adapters.get(iface)
            if meta is None:
                raise RunCommandError("No such device", 1)
            wiphy = meta["phy"].removeprefix("phy")
            stdout = (
                f"Interface {iface}\n"
                f"\taddr {meta['mac']}\n"
                f"\ttype managed\n"
                f"\twiphy {wiphy}\n"
            )
            return CommandResult(stdout=stdout, stderr="", return_code=0)

        if len(joined) >= 4 and joined[0:2] == ["iw", "phy"] and joined[-1] == "info":
            phy_name = joined[2]
            mac = next(
                (
                    meta["mac"]
                    for meta in recorder.adapters.values()
                    if meta["phy"] == phy_name
                ),
                None,
            )
            if mac is None:
                raise RunCommandError("No such device", 1)
            stdout = f"Wiphy {phy_name}\n\taddr {mac}\n"
            return CommandResult(stdout=stdout, stderr="", return_code=0)

        return CommandResult(stdout="", stderr="", return_code=0)

    with hardware_success_mocks(
        interfaces=list(adapters),
        phy_move_side_effect=_move_phy,
    ):
        with patch(
            "wlanpi_core.services.network_namespace_service.interface.delete_interface",
            side_effect=_delete,
        ):
            with patch(
                "wlanpi_core.services.network_namespace_service.phy.list_phys",
                side_effect=lambda namespace=None: (
                    recorder.phys()
                    if namespace is None
                    else [
                        phy_name
                        for phy_name, ns_name in recorder.phy_moves
                        if ns_name == namespace
                    ]
                ),
            ):
                with patch(
                    "wlanpi_core.services.network_namespace_service.run_command",
                    side_effect=_run_command,
                ):
                    yield recorder


def write_json_config(cfg_dir: Path, cfg_id: str, payload: dict) -> Path:
    path = cfg_dir / f"{cfg_id}.json"
    import json

    path.write_text(json.dumps(payload, indent=4))
    return path
