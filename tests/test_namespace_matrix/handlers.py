"""Scenario handlers for namespace_test_matrix.csv rows.

activate_config persist vs rollback paths: tests/scenarios/ACTIVATION_OUTCOMES.md
"""

from __future__ import annotations

import json
import threading
import time
import warnings
from unittest.mock import patch

import pytest

from tests.conftest import (
    JOSH_THREE_RADIO,
    hardware_success_mocks,
    live_adapter_inventory_mocks,
    write_json_config,
)
from tests.scenarios.loader import Scenario
from wlanpi_core.adapters.discovery import LiveInterface
from wlanpi_core.connection.monitor import (
    ConnectionMonitor,
    stop_all_connection_monitors,
)
from wlanpi_core.models.network_config_errors import (
    ConfigActiveError,
    ConfigMalformedError,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.schemas.network.network import (
    NamespaceConfig,
    NetConfig,
    NetConfigUpdate,
    NetSecurity,
    NetworkModeEnum,
    RootConfig,
    SecurityTypes,
)
from wlanpi_core.utils import network_config as nc


def _security(ssid: str, psk: str | None = "secret") -> NetSecurity:
    return NetSecurity(ssid=ssid, security=SecurityTypes.wpa2, psk=psk)


def _root(**kwargs) -> RootConfig:
    base = {
        "mode": NetworkModeEnum.managed,
        "iface_display_name": kwargs.pop(
            "iface_display_name", kwargs.get("interface", "wlan0")
        ),
        "phy": kwargs.pop("phy", "phy0"),
        "interface": kwargs.pop("interface", "wlan0"),
        "default_route": False,
        "autostart_app": None,
        "security": None,
        "mlo": False,
    }
    base.update(kwargs)
    return RootConfig(**base)


def _ns(namespace: str, **kwargs) -> NamespaceConfig:
    root = _root(**kwargs)
    return NamespaceConfig(namespace=namespace, **root.model_dump())


# JOSH_THREE_RADIO as InventoryRecorder.live() reports it: all in root, managed.
JOSH_LIVE: dict[str, tuple[str, str | None, str]] = {
    name: (meta["phy"], None, "managed") for name, meta in JOSH_THREE_RADIO.items()
}


# Layout captured from a WLAN Pi with two MT7921AU USB adapters: onboard phy0
# carries the managed wlan0 plus the wlanpi0 monitor iface on the same MAC.
# MACs are placeholders.
SHARED_PHY_THREE_RADIO: dict[str, dict[str, str]] = {
    "wlan0": {"phy": "phy0", "mac": "00:11:22:33:55:00"},
    "wlanpi0": {"phy": "phy0", "mac": "00:11:22:33:55:00", "type": "monitor"},
    "wlan1": {"phy": "phy1", "mac": "00:11:22:33:55:01"},
    "wlan2": {"phy": "phy2", "mac": "00:11:22:33:55:02"},
}


class _MonitorClock:
    """Fake `time` for connection.monitor only; sleep advances the clock.

    Patching the monitor module's `time.sleep` attribute patches stdlib time
    for every thread (AGENTS.md rule 7). Replacing the module's `time` name
    does not.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._now = 0.0

    def time(self) -> float:
        with self._lock:
            return self._now

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds


def _patch_monitor_clock():
    return patch("wlanpi_core.connection.monitor.time", _MonitorClock())


# --- validation ---


def handle_validate_empty_interface(namespace_service, netcfg_env, scenario: Scenario):
    cfg = RootConfig.model_construct(
        mode=NetworkModeEnum.managed,
        iface_display_name="wlan0",
        phy="phy0",
        interface="",
        default_route=False,
        autostart_app=None,
        security=None,
        mlo=False,
    )
    with patch.object(namespace_service, "get_interfaces", return_value=["wlan0"]):
        result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "interface is required" in result.response.selectErr


def handle_validate_empty_phy(namespace_service, netcfg_env, scenario: Scenario):
    cfg = RootConfig.model_construct(
        mode=NetworkModeEnum.managed,
        iface_display_name="wlan0",
        phy="",
        interface="wlan0",
        default_route=False,
        autostart_app=None,
        security=None,
        mlo=False,
    )
    result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "phy is required" in result.response.selectErr


def handle_validate_empty_iface_display_name(
    namespace_service, netcfg_env, scenario: Scenario
):
    valid, msg = namespace_service._validate_config(
        RootConfig.model_construct(
            mode=NetworkModeEnum.managed,
            iface_display_name="",
            phy="phy0",
            interface="wlan0",
            default_route=False,
            autostart_app=None,
            security=None,
            mlo=False,
        )
    )
    assert valid is False
    assert "iface_display_name" in msg


def handle_validate_invalid_mode(namespace_service, netcfg_env, scenario: Scenario):
    cfg = RootConfig.model_construct(
        mode="adhoc",
        iface_display_name="wlan0",
        phy="phy0",
        interface="wlan0",
        default_route=False,
        autostart_app=None,
        security=None,
        mlo=False,
    )
    with warnings.catch_warnings():
        # intentionally-invalid model; pydantic serializer warnings are expected
        warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
        result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "mode must be one of" in result.response.selectErr


def handle_validate_empty_namespace(namespace_service, netcfg_env, scenario: Scenario):
    cfg = NamespaceConfig.model_construct(
        namespace=" ",
        mode=NetworkModeEnum.managed,
        iface_display_name="wlan0",
        phy="phy0",
        interface="wlan0",
        default_route=False,
        autostart_app=None,
        security=None,
        mlo=False,
    )
    result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "namespace" in result.response.selectErr


def handle_validate_security_missing_ssid(
    namespace_service, netcfg_env, scenario: Scenario
):
    cfg = RootConfig.model_construct(
        mode=NetworkModeEnum.managed,
        iface_display_name="wlan0",
        phy="phy0",
        interface="wlan0",
        default_route=False,
        autostart_app=None,
        mlo=False,
        security=NetSecurity.model_construct(
            ssid="", security=SecurityTypes.wpa2, psk="x"
        ),
    )
    result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "security.ssid" in result.response.selectErr


def handle_validate_wpa2_missing_psk(namespace_service, netcfg_env, scenario: Scenario):
    cfg = _root(
        security=NetSecurity(ssid="MyNet", security=SecurityTypes.wpa2, psk=None)
    )
    result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "security.psk is required" in result.response.selectErr


def handle_validate_invalid_security_type(
    namespace_service, netcfg_env, scenario: Scenario
):
    cfg = RootConfig.model_construct(
        mode=NetworkModeEnum.managed,
        iface_display_name="wlan0",
        phy="phy0",
        interface="wlan0",
        default_route=False,
        autostart_app=None,
        mlo=False,
        security=NetSecurity.model_construct(ssid="x", security="WEP-OLD", psk="x"),
    )
    with warnings.catch_warnings():
        # intentionally-invalid model; pydantic serializer warnings are expected
        warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
        result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "security.security must be one of" in result.response.selectErr


def handle_validate_autostart_app_empty_string(
    namespace_service, netcfg_env, scenario: Scenario
):
    cfg = RootConfig.model_construct(
        mode=NetworkModeEnum.managed,
        iface_display_name="wlan0",
        phy="phy0",
        interface="wlan0",
        default_route=False,
        autostart_app="   ",
        security=None,
        mlo=False,
    )
    result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "autostart_app must be a non-empty string" in result.response.selectErr


def handle_validate_default_route_non_bool(
    namespace_service, netcfg_env, scenario: Scenario
):
    cfg = RootConfig.model_construct(
        mode=NetworkModeEnum.managed,
        iface_display_name="wlan0",
        phy="phy0",
        interface="wlan0",
        default_route="yes",
        autostart_app=None,
        security=None,
        mlo=False,
    )
    with warnings.catch_warnings():
        # intentionally-invalid model; pydantic serializer warnings are expected
        warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
        result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "default_route must be a boolean" in result.response.selectErr


def handle_validate_netconfig_malformed_json(
    namespace_service, netcfg_env, scenario: Scenario
):
    (netcfg_env["cfg_dir"] / "test_bad.json").write_text("{not valid json")
    with pytest.raises(ConfigMalformedError) as exc:
        nc.get_config("test_bad")
    assert exc.value.cfg_id == "test_bad"


def handle_validate_netconfig_empty_file(
    namespace_service, netcfg_env, scenario: Scenario
):
    (netcfg_env["cfg_dir"] / "empty.json").write_text("")
    with pytest.raises(ConfigMalformedError) as exc:
        nc.get_config("empty")
    assert "empty" in exc.value.message.lower()


def handle_validate_netconfig_missing_id(
    namespace_service, netcfg_env, scenario: Scenario
):
    (netcfg_env["cfg_dir"] / "no_id.json").write_text(
        json.dumps({"namespaces": [], "roots": []})
    )
    with pytest.raises(ConfigMalformedError):
        nc.get_config("no_id")


def handle_validate_netconfig_invalid_root_shape(
    namespace_service, netcfg_env, scenario: Scenario
):
    (netcfg_env["cfg_dir"] / "bad_root.json").write_text(
        json.dumps(
            {"id": "bad_root", "namespaces": [], "roots": [{"interface": "wlan0"}]}
        )
    )
    with pytest.raises(ConfigMalformedError):
        nc.get_config("bad_root")


def handle_user_edit_active_config_blocked(
    namespace_service, netcfg_env, scenario: Scenario
):
    write_json_config(
        netcfg_env["cfg_dir"],
        "ns_cfg",
        {"id": "ns_cfg", "namespaces": [], "roots": [_root().model_dump(mode="json")]},
    )
    netcfg_env["ccf"].write_text("ns_cfg")
    with pytest.raises(ConfigActiveError):
        nc.edit_config("ns_cfg", NetConfigUpdate(roots=[]))


# --- filesystem / recovery config ---


def handle_files_current_points_to_deleted(
    namespace_service, netcfg_env, scenario: Scenario
):
    netcfg_env["ccf"].write_text("ghost_cfg")
    with pytest.raises(ConfigMalformedError) as exc:
        nc.recover_current_config()
    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert "invalid or malformed" in exc.value.message.lower()


def handle_list_configs_malformed_annotation(
    namespace_service, netcfg_env, scenario: Scenario
):
    (netcfg_env["cfg_dir"] / "bad.json").write_text("{broken")
    write_json_config(
        netcfg_env["cfg_dir"],
        "good",
        {"id": "good", "namespaces": [], "roots": [_root().model_dump(mode="json")]},
    )
    configs = nc.list_configs()
    assert any("(malformed)" in key for key in configs)
    assert "good" in configs


def handle_files_all_configs_deleted(namespace_service, netcfg_env, scenario: Scenario):
    assert not (netcfg_env["cfg_dir"] / "default.json").exists()
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        cfg = nc.get_default_config()
        loaded = nc.get_config("default")
    assert loaded == cfg
    assert (netcfg_env["cfg_dir"] / "default.json").exists()


def handle_default_created_when_missing(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#202: missing default.json is built from the live iface→phy map."""
    assert not (netcfg_env["cfg_dir"] / "default.json").exists()
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        loaded = nc.get_config("default")
        ok = nc.activate_config("default", override_active=True)
    assert (netcfg_env["cfg_dir"] / "default.json").exists()
    assert loaded.namespaces == []
    assert {root.interface: root.phy for root in loaded.roots or []} == {
        "wlan0": "phy0",
        "wlan1": "phy2",
        "wlan2": "phy1",
    }
    assert all(root.security is None for root in loaded.roots or []), (
        "#202: default must not carry WPA2 without a psk"
    )
    assert ok is True
    assert sorted(inventory.deleted) == [
        ("wlan0", None),
        ("wlan1", None),
        ("wlan2", None),
    ]
    assert sorted(inventory.adds) == [
        ("phy0", "wlan0", None),
        ("phy1", "wlan2", None),
        ("phy2", "wlan1", None),
    ]
    assert inventory.phy_moves == []
    assert inventory.live() == JOSH_LIVE
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_default_legacy_file_migrated(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#202: an untouched pre-fix default.json is replaced from the live inventory."""
    write_json_config(
        netcfg_env["cfg_dir"],
        "default",
        nc._legacy_default_config().model_dump(mode="json"),
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        loaded = nc.get_config("default")
        ok = nc.activate_config("default", override_active=True)
    on_disk = json.loads((netcfg_env["cfg_dir"] / "default.json").read_text())
    assert {r["interface"]: r["phy"] for r in on_disk["roots"]} == {
        "wlan0": "phy0",
        "wlan1": "phy2",
        "wlan2": "phy1",
    }
    assert loaded.model_dump(mode="json") == on_disk
    assert ok is True
    assert inventory.live() == JOSH_LIVE


def handle_default_skips_system_monitors(
    namespace_service, netcfg_env, scenario: Scenario
):
    """Leave SystemManager's wlanpiN monitors out of the live default."""
    with live_adapter_inventory_mocks(SHARED_PHY_THREE_RADIO) as inventory:
        loaded = nc.get_config("default")
        ok = nc.activate_config("default", override_active=True)
    assert [(r.interface, r.phy, r.mode) for r in loaded.roots] == [
        ("wlan2", "phy2", NetworkModeEnum.managed),
        ("wlan1", "phy1", NetworkModeEnum.managed),
        ("wlan0", "phy0", NetworkModeEnum.managed),
    ]
    assert ok is True
    assert not any(name == "wlanpi0" for name, _ns in inventory.deleted)
    assert inventory.live()["wlanpi0"] == ("phy0", None, "monitor")


def handle_default_file_override(namespace_service, netcfg_env, scenario: Scenario):
    custom = {
        "id": "default",
        "namespaces": [],
        "roots": [
            {
                "mode": "monitor",
                "iface_display_name": "wlan0",
                "phy": "phy0",
                "interface": "wlan0",
                "security": None,
                "mlo": False,
                "default_route": False,
                "autostart_app": None,
            }
        ],
    }
    write_json_config(netcfg_env["cfg_dir"], "default", custom)
    loaded = nc.get_config("default")
    assert len(loaded.roots) == 1
    assert loaded.roots[0].mode == NetworkModeEnum.monitor
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        live_default = nc.get_default_config()
    assert loaded.model_dump() != live_default.model_dump()


def handle_default_startup_malformed_current(
    namespace_service, netcfg_env, scenario: Scenario
):
    netcfg_env["ccf"].write_text("")
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        default = nc.get_default_config()
    write_json_config(netcfg_env["cfg_dir"], "default", default.model_dump(mode="json"))
    with pytest.raises(ConfigMalformedError) as exc:
        nc.recover_current_config()
    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert "reverted" in exc.value.message.lower()


# --- activate / service orchestration ---


def _write_netconfig(netcfg_env, cfg_id: str, namespaces=None, roots=None):
    payload = {
        "id": cfg_id,
        "namespaces": namespaces or [],
        "roots": roots or [],
    }
    return write_json_config(netcfg_env["cfg_dir"], cfg_id, payload)


def handle_adapter_interface_not_in_iw_list(
    namespace_service, netcfg_env, scenario: Scenario
):
    roots = [
        _root(interface="wlan9", phy="phy0").model_dump(mode="json"),
        _root(interface="wlan1", phy="phy1", iface_display_name="wlan1").model_dump(
            mode="json"
        ),
    ]
    _write_netconfig(netcfg_env, "missing_iface_cfg", roots=roots)
    with hardware_success_mocks(interfaces=["wlan1"]):
        assert nc.activate_config("missing_iface_cfg", override_active=True) is True


def handle_adapter_phy_declared_not_present(
    namespace_service, netcfg_env, scenario: Scenario
):
    _write_netconfig(
        netcfg_env,
        "stale_phy_cfg",
        namespaces=[
            _ns("stale_ns", interface="wlan2", phy="phy3").model_dump(mode="json")
        ],
        roots=[_root().model_dump(mode="json")],
    )
    with hardware_success_mocks(interfaces=["wlan0"]):
        assert nc.activate_config("stale_phy_cfg", override_active=True) is True


def handle_multi_adapter_one_unplugged_later_ok(
    namespace_service, netcfg_env, scenario: Scenario
):
    _write_netconfig(
        netcfg_env,
        "triple_cfg",
        namespaces=[_ns("ns_b", interface="wlan1", phy="phy1").model_dump(mode="json")],
        roots=[
            _root(security=_security("wlan0")).model_dump(mode="json"),
            _root(interface="wlan2", phy="phy2", iface_display_name="wlan2").model_dump(
                mode="json"
            ),
        ],
    )
    with hardware_success_mocks(interfaces=["wlan0", "wlan1"]):
        assert nc.activate_config("triple_cfg", override_active=True) is True
    assert netcfg_env["ccf"].read_text().strip() == "triple_cfg"


def handle_multi_adapter_one_unplugged_plus_ns_ok(
    namespace_service, netcfg_env, scenario: Scenario
):
    _write_netconfig(
        netcfg_env,
        "mixed_cfg",
        namespaces=[
            _ns(
                "scan_ns", interface="wlan0", phy="phy0", mode=NetworkModeEnum.monitor
            ).model_dump(mode="json")
        ],
        roots=[
            _root(interface="wlan2", phy="phy2", iface_display_name="wlan2").model_dump(
                mode="json"
            )
        ],
    )
    with hardware_success_mocks(interfaces=["wlan0"]):
        assert nc.activate_config("mixed_cfg", override_active=True) is True


def handle_multi_adapter_phy_fault_unacceptable(
    namespace_service, netcfg_env, scenario: Scenario
):
    def fail_phy(phy_name, namespace):
        if phy_name == "phy1":
            raise RunCommandError("move failed", 1)

    _write_netconfig(
        netcfg_env,
        "fault_cfg",
        namespaces=[
            _ns("good_ns", interface="wlan0", phy="phy0").model_dump(mode="json"),
            _ns("bad_ns", interface="wlan1", phy="phy1").model_dump(mode="json"),
        ],
    )
    with hardware_success_mocks(phy_move_side_effect=fail_phy):
        assert nc.activate_config("fault_cfg", override_active=True) is False
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_partial_activation_rollback(
    namespace_service, netcfg_env, scenario: Scenario
):
    def fail_bad_ns(phy_name, namespace):
        if namespace == "bad_ns":
            raise RunCommandError("phy move refused", 1)

    _write_netconfig(
        netcfg_env,
        "bad_cfg",
        namespaces=[
            _ns("good_ns", interface="wlan0", phy="phy0").model_dump(mode="json"),
            _ns("bad_ns", interface="wlan1", phy="phy1").model_dump(mode="json"),
        ],
    )
    deactivate_calls = []

    def track_deactivate(cfg):
        deactivate_calls.append(cfg.interface)

    with hardware_success_mocks(phy_move_side_effect=fail_bad_ns):
        with patch.object(nc.ns, "deactivate_config", side_effect=track_deactivate):
            assert nc.activate_config("bad_cfg", override_active=True) is False
    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert "wlan0" in deactivate_calls


def handle_activation_exception_mid_loop_rollback(
    namespace_service, netcfg_env, scenario: Scenario
):
    """activate_config path 3: exception mid-loop rolls back activated_configs (see ACTIVATION_OUTCOMES.md)."""

    def fail_bring_up(iface_name, namespace=None):
        if namespace == "bad_ns":
            raise RunCommandError("bring up failed", 1)

    _write_netconfig(
        netcfg_env,
        "throw_cfg",
        namespaces=[
            _ns("good_ns", interface="wlan0", phy="phy0").model_dump(mode="json"),
            _ns(
                "bad_ns",
                interface="wlan1",
                phy="phy1",
                iface_display_name="wlan1",
            ).model_dump(mode="json"),
        ],
    )
    deactivate_calls = []

    def track_deactivate(cfg):
        deactivate_calls.append(cfg.interface)

    with hardware_success_mocks():
        with patch(
            "wlanpi_core.services.network_namespace_service.interface.bring_interface_up",
            side_effect=fail_bring_up,
        ):
            with patch.object(nc.ns, "deactivate_config", side_effect=track_deactivate):
                with pytest.raises(RunCommandError):
                    nc.activate_config("throw_cfg", override_active=True)

    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert "wlan0" in deactivate_calls


def handle_deactivate_exception_mid_loop_rollback(
    namespace_service, netcfg_env, scenario: Scenario
):
    """deactivate_config: ccf=default and revert_to_root still run before re-raise on mid-loop failure."""

    _write_netconfig(
        netcfg_env,
        "dual_ns_cfg",
        namespaces=[
            _ns("ns_a", interface="wlan0", phy="phy0").model_dump(mode="json"),
            _ns(
                "ns_b", interface="wlan1", phy="phy1", iface_display_name="wlan1"
            ).model_dump(mode="json"),
        ],
    )
    netcfg_env["ccf"].write_text("dual_ns_cfg")
    revert_calls = []

    def deactivate_side_effect(cfg):
        if cfg.interface == "wlan1":
            raise RunCommandError("deactivate failed", 1)

    with patch.object(nc.ns, "deactivate_config", side_effect=deactivate_side_effect):
        with patch.object(
            nc.ns,
            "revert_to_root",
            side_effect=lambda *a, **k: revert_calls.append(True),
        ):
            with pytest.raises(RunCommandError):
                nc.deactivate_config("dual_ns_cfg", override_active=True)

    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert revert_calls


def handle_dual_ns_split_adapters(namespace_service, netcfg_env, scenario: Scenario):
    _write_netconfig(
        netcfg_env,
        "split_cfg",
        namespaces=[
            _ns("ns_a", interface="wlan0", phy="phy0").model_dump(mode="json"),
            _ns(
                "ns_b", interface="wlan1", phy="phy1", iface_display_name="wlan1"
            ).model_dump(mode="json"),
        ],
    )
    with hardware_success_mocks():
        assert nc.activate_config("split_cfg", override_active=True) is True
    assert netcfg_env["ccf"].read_text().strip() == "split_cfg"


def handle_move_wlan1_to_ns_orb_no_security(
    namespace_service, netcfg_env, scenario: Scenario
):
    cfg = _ns(
        "scan_ns",
        interface="wlan1",
        phy="phy1",
        iface_display_name="wlan1",
        mode=NetworkModeEnum.monitor,
        autostart_app="orb",
    )
    with hardware_success_mocks():
        with patch(
            "wlanpi_core.services.network_namespace_service.apps.start_app_in_namespace",
            return_value=True,
        ) as start_app:
            result = nc.ns.activate_config(cfg)
            start_app.assert_called_once()
    assert result.status == "connected"


def handle_user_manual_namespace_exists(
    namespace_service, netcfg_env, scenario: Scenario
):
    cfg = _ns("my_ns", interface="wlan1", phy="phy1", iface_display_name="wlan1")
    with hardware_success_mocks():
        with patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.namespace_exists",
            return_value=True,
        ) as exists:
            with patch(
                "wlanpi_core.services.network_namespace_service.ns_namespace.create_namespace",
            ) as create_ns:
                live = LiveInterface("wlan1", 1, None, "managed")
                assert namespace_service._prepare_namespace(cfg, live) is True
                exists.assert_called_once_with("my_ns")
                create_ns.assert_not_called()


def handle_ssid_prestage_immediate_provisioned(
    namespace_service, netcfg_env, scenario: Scenario
):
    cfg = _root(security=_security("HiddenNet"))
    with hardware_success_mocks():
        with patch.object(namespace_service, "_monitor_connection_async") as monitor:
            result = namespace_service.activate_config(cfg)
            monitor.assert_called_once()
    assert result.status == "provisioned"


def handle_ssid_delayed_multi_adapter_no_fault(
    namespace_service, netcfg_env, scenario: Scenario
):
    _write_netconfig(
        netcfg_env,
        "dual_prestage_cfg",
        namespaces=[
            _ns(
                "ns_a", interface="wlan0", phy="phy0", security=_security("LateNet")
            ).model_dump(mode="json"),
            _ns(
                "ns_b",
                interface="wlan1",
                phy="phy1",
                iface_display_name="wlan1",
                mode=NetworkModeEnum.monitor,
            ).model_dump(mode="json"),
        ],
    )
    with hardware_success_mocks():
        assert nc.activate_config("dual_prestage_cfg", override_active=True) is True


def handle_default_return_via_deactivate(
    namespace_service, netcfg_env, scenario: Scenario
):
    _write_netconfig(
        netcfg_env,
        "custom_ns_cfg",
        namespaces=[
            _ns(
                "test_ns", interface="wlan0", phy="phy0", security=_security("test")
            ).model_dump(mode="json")
        ],
        roots=[
            _root(interface="wlan1", phy="phy1", iface_display_name="wlan1").model_dump(
                mode="json"
            )
        ],
    )
    netcfg_env["ccf"].write_text("custom_ns_cfg")
    with hardware_success_mocks():
        with patch.object(nc.ns, "revert_to_root") as revert:
            assert nc.deactivate_config("custom_ns_cfg", override_active=True) is True
            revert.assert_any_call(None)
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_user_broken_active_override_deactivate(
    namespace_service, netcfg_env, scenario: Scenario
):
    _write_netconfig(
        netcfg_env,
        "broken_cfg",
        namespaces=[
            _ns("orphan_ns", interface="wlan0", phy="phy0").model_dump(mode="json")
        ],
    )
    netcfg_env["ccf"].write_text("broken_cfg")
    with patch.object(nc.ns, "deactivate_config"):
        with patch.object(nc.ns, "revert_to_root") as revert:
            assert nc.deactivate_config("broken_cfg", override_active=True) is True
            revert.assert_any_call(None)
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_user_manual_phy_move_then_recover(
    namespace_service, netcfg_env, scenario: Scenario
):
    _write_netconfig(
        netcfg_env,
        "ns_cfg",
        namespaces=[
            _ns("my_ns", interface="wlan0", phy="phy0").model_dump(mode="json")
        ],
    )
    netcfg_env["ccf"].write_text("ns_cfg")
    with patch.object(nc.ns, "deactivate_config"):
        with patch.object(nc.ns, "revert_to_root") as revert:
            assert nc.deactivate_config("ns_cfg", override_active=True) is True
            revert.assert_any_call(None)


# --- connection monitor ---


def _wait_for_monitors_idle(timeout_seconds: float = 5.0) -> None:
    """Wait until no ConnectionMonitor registry entries or threads remain.

    Fails loudly instead of returning silently: a leftover monitor thread from
    one scenario keeps doing module-attribute lookups and consumes the next
    scenario's mocks, which surfaces as unrelated flaky failures.
    """
    from wlanpi_core.connection import monitor as mon

    registry_empty = False
    zombies: list[str] = []
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with mon._monitor_lock:
            registry_empty = not mon._connection_monitors
        zombies = [
            t.name
            for t in threading.enumerate()
            if t.name.startswith("ConnectionMonitor-") and t.is_alive()
        ]
        if registry_empty and not zombies:
            return
        time.sleep(0.05)
    raise RuntimeError(
        f"ConnectionMonitor cleanup timed out: registry_empty={registry_empty}, "
        f"zombie_threads={zombies}"
    )


def handle_ssid_delayed_connect_within_monitor(
    namespace_service, netcfg_env, scenario: Scenario
):
    stop_all_connection_monitors()
    _wait_for_monitors_idle()
    cfg = _ns(
        "ns_a",
        interface="wlan0",
        phy="phy0",
        security=_security("LateNet"),
        autostart_app="orb",
        default_route=True,
    )
    status_sequence = [
        {"wpa_status": {"wpa_state": "SCANNING"}},
        {"wpa_status": {"wpa_state": "SCANNING"}},
        {"wpa_status": {"wpa_state": "COMPLETED"}},
    ]

    seq_lock = threading.Lock()
    seq_state = {"i": 0}

    def wpa_side_effect(*args, **kwargs):
        with seq_lock:
            i = seq_state["i"]
            seq_state["i"] = i + 1
        if i < len(status_sequence):
            return status_sequence[i]
        return {"wpa_status": {"wpa_state": "COMPLETED"}}

    app_started = threading.Event()

    with patch(
        "wlanpi_core.connection.monitor.get_wpa_status", side_effect=wpa_side_effect
    ):
        with _patch_monitor_clock():
            with patch(
                "wlanpi_core.connection.monitor.restart_dhcp_with_timeout"
            ) as dhcp:
                with patch("wlanpi_core.connection.monitor.set_default_route"):
                    with patch(
                        "wlanpi_core.namespaces.apps.start_app_in_namespace",
                        side_effect=lambda *a, **k: app_started.set(),
                    ) as start_app:
                        ConnectionMonitor.start_monitor(cfg, "wlan0", "ns_a", timeout=5)
                        app_ran = app_started.wait(timeout=5)
                        # clean up BEFORE asserting so a failure cannot leak
                        # a running monitor thread into the next test
                        stop_all_connection_monitors()
                        _wait_for_monitors_idle()
    assert app_ran, "start_app_in_namespace not called within 5s"
    dhcp.assert_called_once()
    start_app.assert_called_once_with("ns_a", "orb")


def handle_ssid_delayed_beyond_monitor_timeout(
    namespace_service, netcfg_env, scenario: Scenario
):
    stop_all_connection_monitors()
    _wait_for_monitors_idle()
    cfg = _root(
        security=_security("VeryLateNet"),
        autostart_app="orb",
    )
    with patch(
        "wlanpi_core.connection.monitor.get_wpa_status",
        return_value={"wpa_status": {"wpa_state": "SCANNING"}},
    ) as wpa:
        with patch("wlanpi_core.connection.monitor.restart_dhcp_with_timeout") as dhcp:
            with patch(
                "wlanpi_core.namespaces.apps.start_app_in_namespace"
            ) as start_app:
                with _patch_monitor_clock():
                    ConnectionMonitor.start_monitor(cfg, "wlan0", None, timeout=15)
                    # No stop request: the monitor must exit through its own
                    # timeout branch. Raises if the thread never finishes.
                    _wait_for_monitors_idle()
    # One poll per fake second for 15 s proves the timeout path ran, not the
    # stop-event path.
    assert wpa.call_count == 15
    dhcp.assert_not_called()
    start_app.assert_not_called()


def handle_move_wlan1_to_ns_with_orb_monitor(
    namespace_service, netcfg_env, scenario: Scenario
):
    _write_netconfig(
        netcfg_env,
        "ns_orb_cfg",
        namespaces=[
            _ns(
                "orb_ns",
                interface="wlan1",
                phy="phy1",
                iface_display_name="wlan1",
                security=_security("orbnet"),
            ).model_dump(mode="json")
        ],
        roots=[_root(security=_security("rootnet")).model_dump(mode="json")],
    )
    with hardware_success_mocks():
        with patch.object(nc.ns, "_monitor_connection_async") as monitor:
            assert nc.activate_config("ns_orb_cfg", override_active=True) is True
            assert monitor.call_count >= 1


def handle_files_apps_json_missing_orb(
    namespace_service, netcfg_env, scenario: Scenario
):
    """Missing orb in apps.json: monitor calls start_app; ValueError is caught gracefully."""
    stop_all_connection_monitors()
    _wait_for_monitors_idle()
    cfg = _ns(
        "orb_ns",
        interface="wlan1",
        phy="phy1",
        iface_display_name="wlan1",
        autostart_app="orb",
    )
    app_called = threading.Event()

    def missing_app(*args, **kwargs):
        try:
            raise ValueError("App ID orb not found in apps file")
        finally:
            app_called.set()

    with patch(
        "wlanpi_core.connection.monitor.get_wpa_status",
        return_value={"wpa_status": {"wpa_state": "COMPLETED"}},
    ):
        with patch("wlanpi_core.connection.monitor.restart_dhcp_with_timeout"):
            with patch("wlanpi_core.connection.monitor.set_default_route"):
                with patch(
                    "wlanpi_core.namespaces.apps.start_app_in_namespace",
                    side_effect=missing_app,
                ) as start_app:
                    with _patch_monitor_clock():
                        ConnectionMonitor.start_monitor(
                            cfg, "wlan1", "orb_ns", timeout=5
                        )
                        app_ran = app_called.wait(timeout=5)
                        # clean up BEFORE asserting so a failure cannot leak
                        # a running monitor thread into the next test
                        stop_all_connection_monitors()
                        _wait_for_monitors_idle()
    assert app_ran, "start_app_in_namespace not called within 5s"
    start_app.assert_called_once_with("orb_ns", "orb")


# --- identity: live iface→phy map vs stored cfg.phy ---
#
# Expected sequences are the contract for the #236 fix: resolve the live
# (phy, netns) of the iface first, delete it where it lives, move the live phy
# if needed, then re-add the iface there with the configured mode. Stale rows
# configure mode=monitor over a managed live iface so a prepare that does
# nothing cannot pass.


def handle_stale_phy_iface_on_other_radio(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#236: stored phy1 for wlan1 while live wiphy is phy2 must not steal phy1."""
    _write_netconfig(
        netcfg_env,
        "stale_phy_cfg",
        roots=[
            _root(
                interface="wlan1", phy="phy1", mode=NetworkModeEnum.monitor
            ).model_dump(mode="json")
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        ok = nc.activate_config("stale_phy_cfg", override_active=True)
    assert ok is True
    assert inventory.deleted == [("wlan1", None)]
    assert inventory.adds == [("phy2", "wlan1", None)]
    assert inventory.phy_moves == []
    assert inventory.live() == {**JOSH_LIVE, "wlan1": ("phy2", None, "monitor")}
    assert netcfg_env["ccf"].read_text().strip() == "stale_phy_cfg"


def handle_phy_index_neq_iface_index(namespace_service, netcfg_env, scenario: Scenario):
    """Control: non-parity indexes succeed when cfg.phy matches live."""
    _write_netconfig(
        netcfg_env,
        "live_map_cfg",
        roots=[
            _root(interface=name, phy=meta["phy"]).model_dump(mode="json")
            for name, meta in JOSH_THREE_RADIO.items()
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        ok = nc.activate_config("live_map_cfg", override_active=True)
    assert ok is True
    assert inventory.deleted == [("wlan0", None), ("wlan1", None), ("wlan2", None)]
    assert inventory.adds == [
        ("phy0", "wlan0", None),
        ("phy2", "wlan1", None),
        ("phy1", "wlan2", None),
    ]
    assert inventory.phy_moves == []
    assert inventory.live() == JOSH_LIVE
    assert netcfg_env["ccf"].read_text().strip() == "live_map_cfg"


def handle_prepare_missing_phy_after_delete(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#236: missing cfg.phy must not leave the live iface deleted."""
    _write_netconfig(
        netcfg_env,
        "missing_phy_cfg",
        roots=[
            _root(
                interface="wlan1", phy="phy9", mode=NetworkModeEnum.monitor
            ).model_dump(mode="json")
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        ok = nc.activate_config("missing_phy_cfg", override_active=True)
    assert ok is True
    assert inventory.deleted == [("wlan1", None)]
    assert inventory.adds == [("phy2", "wlan1", None)]
    assert inventory.phy_moves == []
    assert inventory.live() == {**JOSH_LIVE, "wlan1": ("phy2", None, "monitor")}


def handle_stale_phy_namespace_wrong_radio(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#236 namespace twin: move phy2 (live wlan1), not the stored phy1."""
    _write_netconfig(
        netcfg_env,
        "stale_ns_cfg",
        namespaces=[
            _ns(
                "lab_ns",
                interface="wlan1",
                phy="phy1",
                mode=NetworkModeEnum.monitor,
            ).model_dump(mode="json")
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        ok = nc.activate_config("stale_ns_cfg", override_active=True)
    assert ok is True
    assert inventory.deleted == [("wlan1", None)]
    assert inventory.phy_moves == [("phy2", "lab_ns")]
    assert inventory.adds == [("phy2", "wlan1", "lab_ns")]
    assert inventory.live() == {**JOSH_LIVE, "wlan1": ("phy2", "lab_ns", "monitor")}


def handle_default_single_radio_no_500(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#202: activate default on a single-radio device must persist, not fail."""
    single = {"wlan0": {"phy": "phy0", "mac": "00:11:22:33:44:00"}}
    with live_adapter_inventory_mocks(single) as inventory:
        ok = nc.activate_config("default", override_active=True)
    assert ok is True, (
        "#202: activate default returned False on single-radio "
        "(hardcoded wlan1 and/or fake WPA2)"
    )
    default = json.loads((netcfg_env["cfg_dir"] / "default.json").read_text())
    assert [(r["interface"], r["phy"]) for r in default["roots"]] == [("wlan0", "phy0")]
    assert inventory.deleted == [("wlan0", None)]
    assert inventory.adds == [("phy0", "wlan0", None)]
    assert inventory.live() == {"wlan0": ("phy0", None, "managed")}
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_create_profile_snapshots_mac(
    namespace_service, netcfg_env, scenario: Scenario
):
    """Jake pin: first profile using wlan1 snapshots the live MAC."""
    cfg = NetConfig(
        id="pin_wlan1",
        namespaces=[],
        roots=[
            _root(interface="wlan1", phy="phy1", iface_display_name="wlan1"),
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        assert nc.add_config(cfg) is True
        loaded = nc.get_config("pin_wlan1")
    dumped = loaded.roots[0].model_dump()
    mac = dumped.get("mac")
    expected = JOSH_THREE_RADIO["wlan1"]["mac"]
    assert mac == expected, (
        f"#237: add_config did not snapshot live MAC; got {mac!r}, expected {expected}"
    )


def handle_iface_already_in_netns_at_activation(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#236: a root cfg for an iface left in another netns brings it home."""
    adapters = {
        **JOSH_THREE_RADIO,
        "wlan1": {**JOSH_THREE_RADIO["wlan1"], "netns": "old_ns"},
    }
    _write_netconfig(
        netcfg_env,
        "home_cfg",
        roots=[_root(interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(adapters) as inventory:
        ok = nc.activate_config("home_cfg", override_active=True)
    assert ok is True
    assert inventory.deleted == [("wlan1", "old_ns")]
    assert inventory.phy_moves == [("phy2", None)]
    assert inventory.adds == [("phy2", "wlan1", None)]
    assert inventory.live() == JOSH_LIVE


def handle_phy10_vs_phy1_substring(namespace_service, netcfg_env, scenario: Scenario):
    """#236: phy1 outside root must not look present because phy10 is."""
    adapters = {
        "wlan0": {"phy": "phy0", "mac": "00:11:22:33:44:00"},
        "wlan1": {"phy": "phy1", "mac": "00:11:22:33:44:01", "netns": "old_ns"},
        "wlan10": {"phy": "phy10", "mac": "00:11:22:33:44:10"},
    }
    _write_netconfig(
        netcfg_env,
        "phy1_cfg",
        roots=[_root(interface="wlan1", phy="phy1").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(adapters) as inventory:
        ok = nc.activate_config("phy1_cfg", override_active=True)
    assert ok is True
    assert inventory.deleted == [("wlan1", "old_ns")]
    assert inventory.phy_moves == [("phy1", None)]
    assert inventory.adds == [("phy1", "wlan1", None)]
    assert inventory.live() == {
        "wlan0": ("phy0", None, "managed"),
        "wlan1": ("phy1", None, "managed"),
        "wlan10": ("phy10", None, "managed"),
    }


def handle_iface_display_name_differs(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#236: re-activating finds the iface by iface_display_name too."""
    adapters = {
        "wlan0": JOSH_THREE_RADIO["wlan0"],
        "lab1": JOSH_THREE_RADIO["wlan1"],
        "wlan2": JOSH_THREE_RADIO["wlan2"],
    }
    _write_netconfig(
        netcfg_env,
        "renamed_cfg",
        roots=[
            _root(
                interface="wlan1",
                iface_display_name="lab1",
                phy="phy2",
                mode=NetworkModeEnum.monitor,
            ).model_dump(mode="json")
        ],
    )
    with live_adapter_inventory_mocks(adapters) as inventory:
        ok = nc.activate_config("renamed_cfg", override_active=True)
    assert ok is True
    assert inventory.deleted == [("lab1", None)]
    assert inventory.adds == [("phy2", "lab1", None)]
    assert inventory.live() == {
        "lab1": ("phy2", None, "monitor"),
        "wlan0": ("phy0", None, "managed"),
        "wlan2": ("phy1", None, "managed"),
    }


def handle_shared_phy_monitor_iface_round_trip(
    namespace_service, netcfg_env, scenario: Scenario
):
    """Bring wlanpi0 back with wlan0 when phy0 round-trips through a netns."""
    _write_netconfig(
        netcfg_env,
        "shared_cfg",
        namespaces=[
            _ns("lab_ns", interface="wlan0", phy="phy0").model_dump(mode="json")
        ],
    )
    with live_adapter_inventory_mocks(SHARED_PHY_THREE_RADIO) as inventory:
        # Same order as real `iw dev`: phys high to low, newest iface first.
        assert namespace_service.get_interfaces() == [
            "wlan2",
            "wlan1",
            "wlanpi0",
            "wlan0",
        ]
        assert nc.activate_config("shared_cfg", override_active=True) is True
        after_activate = inventory.live()
        assert nc.deactivate_config("shared_cfg") is True
    assert after_activate == {
        "wlan1": ("phy1", None, "managed"),
        "wlan2": ("phy2", None, "managed"),
        "wlan0": ("phy0", "lab_ns", "managed"),
        "wlanpi0": ("phy0", "lab_ns", "monitor"),
    }
    assert inventory.live() == {
        name: (meta["phy"], None, meta.get("type", "managed"))
        for name, meta in SHARED_PHY_THREE_RADIO.items()
    }
    assert not any(name == "wlanpi0" for name, _ns in inventory.deleted)
    assert not any(name == "wlanpi0" for _phy, name, _ns in inventory.adds)
    assert "lab_ns" not in inventory.netns
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_rollback_after_partial_prepare(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#236: a prepare that fails after moving its phy is rolled back with the rest."""
    _write_netconfig(
        netcfg_env,
        "partial_cfg",
        namespaces=[
            _ns("good_ns", interface="wlan0", phy="phy0").model_dump(mode="json"),
            _ns("bad_ns", interface="wlan1", phy="phy2").model_dump(mode="json"),
        ],
    )
    faults = {
        ("bad_ns", ("ip", "link", "set", "wlan1", "up")): (
            "RTNETLINK answers: Operation not possible due to RF-kill\n"
        )
    }
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO, faults=faults) as inventory:
        with pytest.raises(RunCommandError):
            nc.activate_config("partial_cfg", override_active=True)
    assert inventory.live() == JOSH_LIVE
    assert not inventory.netns & {"good_ns", "bad_ns"}
    assert netcfg_env["ccf"].read_text().strip() == "default"


HANDLERS = {
    "default_created_when_missing": handle_default_created_when_missing,
    "default_legacy_file_migrated": handle_default_legacy_file_migrated,
    "default_skips_system_monitors": handle_default_skips_system_monitors,
    "default_file_override": handle_default_file_override,
    "dual_ns_split_adapters": handle_dual_ns_split_adapters,
    "move_wlan1_to_ns_orb_no_security": handle_move_wlan1_to_ns_orb_no_security,
    "move_wlan1_to_ns_with_orb_monitor": handle_move_wlan1_to_ns_with_orb_monitor,
    "user_manual_namespace_exists": handle_user_manual_namespace_exists,
    "default_return_via_deactivate": handle_default_return_via_deactivate,
    "default_startup_malformed_current": handle_default_startup_malformed_current,
    "files_current_points_to_deleted": handle_files_current_points_to_deleted,
    "user_broken_active_override_deactivate": handle_user_broken_active_override_deactivate,
    "user_manual_phy_move_then_recover": handle_user_manual_phy_move_then_recover,
    "adapter_interface_not_in_iw_list": handle_adapter_interface_not_in_iw_list,
    "adapter_phy_declared_not_present": handle_adapter_phy_declared_not_present,
    "multi_adapter_one_unplugged_later_ok": handle_multi_adapter_one_unplugged_later_ok,
    "multi_adapter_one_unplugged_plus_ns_ok": handle_multi_adapter_one_unplugged_plus_ns_ok,
    "multi_adapter_phy_fault_unacceptable": handle_multi_adapter_phy_fault_unacceptable,
    "partial_activation_rollback": handle_partial_activation_rollback,
    "activation_exception_mid_loop_rollback": handle_activation_exception_mid_loop_rollback,
    "deactivate_exception_mid_loop_rollback": handle_deactivate_exception_mid_loop_rollback,
    "ssid_delayed_beyond_monitor_timeout": handle_ssid_delayed_beyond_monitor_timeout,
    "ssid_delayed_connect_within_monitor": handle_ssid_delayed_connect_within_monitor,
    "ssid_delayed_multi_adapter_no_fault": handle_ssid_delayed_multi_adapter_no_fault,
    "ssid_prestage_immediate_provisioned": handle_ssid_prestage_immediate_provisioned,
    "user_edit_active_config_blocked": handle_user_edit_active_config_blocked,
    "validate_autostart_app_empty_string": handle_validate_autostart_app_empty_string,
    "validate_default_route_non_bool": handle_validate_default_route_non_bool,
    "validate_empty_iface_display_name": handle_validate_empty_iface_display_name,
    "validate_empty_interface": handle_validate_empty_interface,
    "validate_empty_namespace": handle_validate_empty_namespace,
    "validate_empty_phy": handle_validate_empty_phy,
    "validate_invalid_mode": handle_validate_invalid_mode,
    "validate_invalid_security_type": handle_validate_invalid_security_type,
    "validate_netconfig_empty_file": handle_validate_netconfig_empty_file,
    "validate_netconfig_invalid_root_shape": handle_validate_netconfig_invalid_root_shape,
    "validate_netconfig_malformed_json": handle_validate_netconfig_malformed_json,
    "validate_netconfig_missing_id": handle_validate_netconfig_missing_id,
    "validate_security_missing_ssid": handle_validate_security_missing_ssid,
    "validate_wpa2_missing_psk": handle_validate_wpa2_missing_psk,
    "files_all_configs_deleted": handle_files_all_configs_deleted,
    "list_configs_malformed_annotation": handle_list_configs_malformed_annotation,
    "files_apps_json_missing_orb": handle_files_apps_json_missing_orb,
    "stale_phy_iface_on_other_radio": handle_stale_phy_iface_on_other_radio,
    "phy_index_neq_iface_index": handle_phy_index_neq_iface_index,
    "prepare_missing_phy_after_delete": handle_prepare_missing_phy_after_delete,
    "stale_phy_namespace_wrong_radio": handle_stale_phy_namespace_wrong_radio,
    "default_single_radio_no_500": handle_default_single_radio_no_500,
    "create_profile_snapshots_mac": handle_create_profile_snapshots_mac,
    "iface_already_in_netns_at_activation": handle_iface_already_in_netns_at_activation,
    "phy10_vs_phy1_substring": handle_phy10_vs_phy1_substring,
    "iface_display_name_differs": handle_iface_display_name_differs,
    "rollback_after_partial_prepare": handle_rollback_after_partial_prepare,
    "shared_phy_monitor_iface_round_trip": handle_shared_phy_monitor_iface_round_trip,
}


def run_scenario(scenario: Scenario, namespace_service, netcfg_env):
    handler = HANDLERS.get(scenario.name)
    if handler is None:
        pytest.fail(f"No handler registered for scenario {scenario.name}")
    handler(namespace_service, netcfg_env, scenario)
