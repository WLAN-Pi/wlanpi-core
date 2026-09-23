"""Scenario handlers for namespace_test_matrix.csv rows.

activate_config persist vs rollback paths: tests/scenarios/ACTIVATION_OUTCOMES.md
"""

from __future__ import annotations

import json
import threading
import time
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError as PydanticValidationError

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
    ConfigBusyError,
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


def _security(ssid: str, psk: str | None = "secret-passphrase") -> NetSecurity:
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


def _mark_core_namespace(name: str) -> None:
    """Record `name` as created by Core, as _prepare_namespace would."""
    from wlanpi_core.services import network_namespace_service as nns

    # Call inside live_adapter_inventory_mocks, which supplies the identity.
    marker = Path(nns.RUN_DIR) / "netns" / name
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(nc.ns._netns_id(name) or "")


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
    # The drivers created these netdevs, not Core, so applying the default
    # leaves them alone (P14): nothing deleted, added or moved.
    assert inventory.deleted == []
    assert inventory.adds == []
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
    # dhcpcd is left waiting in the background for a late association; the
    # app still needs a confirmed connection.
    dhcp.assert_called_once_with("wlan0", None, timeout=1, default_route=False)
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
    # wlan0 was created by its driver, so the default leaves it alone (P14).
    assert inventory.deleted == []
    assert inventory.adds == []
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
    """#236: a root cfg for an iface left in a Core netns brings it home."""
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
        _mark_core_namespace("old_ns")  # left by an earlier Core activation
        ok = nc.activate_config("home_cfg", override_active=True)
    assert ok is True
    # Tearing down the active default (#271) brings wlan1 home from the
    # leftover Core namespace; the new profile's prepare then recreates it.
    assert inventory.deleted == [("wlan1", "old_ns"), ("wlan1", None)]
    assert inventory.phy_moves == [("phy2", None)]
    assert inventory.adds == [("phy2", "wlan1", None), ("phy2", "wlan1", None)]
    assert inventory.live() == JOSH_LIVE
    assert "old_ns" not in inventory.netns


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
        _mark_core_namespace("old_ns")  # left by an earlier Core activation
        ok = nc.activate_config("phy1_cfg", override_active=True)
    assert ok is True
    # As in iface_already_in_netns_at_activation: default teardown returns
    # phy1 from the leftover Core namespace, then prepare recreates wlan1.
    assert inventory.deleted == [("wlan1", "old_ns"), ("wlan1", None)]
    assert inventory.phy_moves == [("phy1", None)]
    assert inventory.adds == [("phy1", "wlan1", None), ("phy1", "wlan1", None)]
    assert "old_ns" not in inventory.netns
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


def handle_revert_leaves_foreign_namespace(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#275: deactivate returns Core's namespaces and leaves others alone."""
    adapters = {
        **JOSH_THREE_RADIO,
        "wlan2": {**JOSH_THREE_RADIO["wlan2"], "netns": "user_ns"},
    }
    _write_netconfig(
        netcfg_env,
        "core_cfg",
        namespaces=[_ns("ns_a", interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(adapters) as inventory:
        assert nc.activate_config("core_cfg", override_active=True) is True
        assert nc.deactivate_config("core_cfg") is True
    assert inventory.live() == {
        "wlan0": ("phy0", None, "managed"),
        "wlan1": ("phy2", None, "managed"),
        "wlan2": ("phy1", "user_ns", "managed"),
    }
    assert inventory.netns == {"user_ns"}


def handle_revert_moves_phy_without_netdev(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#275: a phy with no netdev left in a Core namespace still returns to root."""
    _write_netconfig(
        netcfg_env,
        "core_cfg",
        namespaces=[_ns("ns_a", interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        assert nc.activate_config("core_cfg", override_active=True) is True
        # Someone deletes the netdev inside the namespace behind Core's back.
        inventory.run_command(
            ["sudo", "ip", "netns", "exec", "ns_a", "/sbin/iw", "dev", "wlan1", "del"]
        )
        assert nc.deactivate_config("core_cfg") is True
    # Moved explicitly before the namespace is deleted, not returned by the
    # kernel as a side effect of destroying a non-empty namespace.
    assert inventory.phy_moves[-1] == ("phy2", None)
    assert inventory.phy_netns["phy2"] is None
    assert "ns_a" not in inventory.netns


def _netconfig_error(namespaces=(), roots=()) -> str:
    with pytest.raises(PydanticValidationError) as exc:
        NetConfig(
            id="dup",
            namespaces=[_ns(ns, **kw) for ns, kw in namespaces],
            roots=[_root(**kw) for kw in roots],
        )
    return str(exc.value)


def handle_validate_duplicate_interface(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#273: two entries cannot claim the same live radio."""
    msg = _netconfig_error(
        namespaces=[("ns_a", {"interface": "wlan1", "phy": "phy1"})],
        roots=[{"interface": "wlan1", "phy": "phy1"}],
    )
    assert "interface used by more than one entry" in msg


def handle_validate_display_name_shadows_interface(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#273: a display name may not be another entry's interface."""
    msg = _netconfig_error(
        roots=[
            {"interface": "wlan0", "phy": "phy0", "iface_display_name": "wlan1"},
            {"interface": "wlan1", "phy": "phy1"},
        ],
    )
    assert "is another entry's interface" in msg


def handle_validate_same_name_other_namespace_ok(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#273: the same display name in two namespaces is allowed; runtime state is per netns."""
    cfg = NetConfig(
        id="mon",
        namespaces=[
            _ns("ns_a", interface="wlan1", phy="phy1", iface_display_name="mon0"),
            _ns("ns_b", interface="wlan2", phy="phy2", iface_display_name="mon0"),
        ],
        roots=[],
    )
    assert len(cfg.namespaces) == 2
    msg = _netconfig_error(
        namespaces=[
            (
                "ns_a",
                {"interface": "wlan1", "phy": "phy1", "iface_display_name": "mon0"},
            ),
            (
                "ns_a",
                {"interface": "wlan2", "phy": "phy2", "iface_display_name": "mon0"},
            ),
        ],
    )
    assert "used twice in one namespace" in msg


def handle_same_display_name_two_namespaces(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#273: sta0 in ns_a must not be taken for the second entry's radio."""
    _write_netconfig(
        netcfg_env,
        "sta_cfg",
        namespaces=[
            _ns(
                "ns_a", interface="wlan1", phy="phy2", iface_display_name="sta0"
            ).model_dump(mode="json"),
            _ns(
                "ns_b", interface="wlan2", phy="phy1", iface_display_name="sta0"
            ).model_dump(mode="json"),
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        assert nc.activate_config("sta_cfg", override_active=True) is True
        after = {(ns, name): meta.phy for (ns, name), meta in inventory.ifaces.items()}
        assert nc.deactivate_config("sta_cfg") is True
    assert after == {
        (None, "wlan0"): "phy0",
        ("ns_a", "sta0"): "phy2",
        ("ns_b", "sta0"): "phy1",
    }
    assert inventory.phy_moves[:2] == [("phy2", "ns_a"), ("phy1", "ns_b")]
    assert inventory.live() == JOSH_LIVE


def handle_namespace_private_resolv_conf(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#273: Core namespaces get /etc/netns/<ns>/resolv.conf; it goes with them."""
    from wlanpi_core.services import network_namespace_service as nns

    etc = Path(nns.NETNS_ETC_DIR)
    _write_netconfig(
        netcfg_env,
        "dns_cfg",
        namespaces=[_ns("ns_a", interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        assert nc.activate_config("dns_cfg", override_active=True) is True
        assert (etc / "ns_a" / "resolv.conf").is_file()
        assert nc.deactivate_config("dns_cfg") is True
    assert not (etc / "ns_a").exists()


def handle_concurrent_activate_rejected(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#270: a second change while one is running fails fast with ConfigBusyError."""
    _write_netconfig(
        netcfg_env,
        "slow_cfg",
        roots=[_root(interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    entered = threading.Event()
    release = threading.Event()
    real_activate = nc.ns.activate_config

    def blocking_activate(cfg):
        entered.set()
        assert release.wait(timeout=5), "test never released the first activation"
        return real_activate(cfg)

    results: dict[str, object] = {}

    def first():
        try:
            results["first"] = nc.activate_config("slow_cfg", override_active=True)
        except Exception as e:  # surfaced by the assertion below
            results["first"] = e

    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        with patch.object(nc.ns, "activate_config", side_effect=blocking_activate):
            worker = threading.Thread(target=first, name="first-activation")
            worker.start()
            try:
                assert entered.wait(timeout=5), "first activation never started"
                with pytest.raises(ConfigBusyError):
                    nc.activate_config("slow_cfg", override_active=True)
                with pytest.raises(ConfigBusyError):
                    nc.deactivate_config("slow_cfg", override_active=True)
            finally:
                release.set()
                worker.join(timeout=5)
            if worker.is_alive():
                raise AssertionError("first activation thread did not finish")
        assert results["first"] is True
        # The lock is released afterwards.
        assert nc.deactivate_config("slow_cfg") is True


def handle_override_tears_down_previous(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#271: activating B with override first tears down active profile A."""
    _write_netconfig(
        netcfg_env,
        "prof_a",
        namespaces=[
            _ns(
                "ns_x", interface="wlan2", phy="phy1", mode=NetworkModeEnum.monitor
            ).model_dump(mode="json")
        ],
    )
    _write_netconfig(
        netcfg_env,
        "prof_b",
        roots=[_root(interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        assert nc.activate_config("prof_a", override_active=True) is True
        assert inventory.live()["wlan2"] == ("phy1", "ns_x", "monitor")
        assert nc.activate_config("prof_b", override_active=True) is True
    assert inventory.live() == JOSH_LIVE
    assert "ns_x" not in inventory.netns
    assert netcfg_env["ccf"].read_text().strip() == "prof_b"


def handle_failed_override_falls_back_to_default(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#271: a failed override leaves default recorded and applied, not a stale pointer."""
    _write_netconfig(
        netcfg_env,
        "prof_a",
        namespaces=[
            _ns(
                "ns_x", interface="wlan2", phy="phy1", mode=NetworkModeEnum.monitor
            ).model_dump(mode="json")
        ],
    )
    _write_netconfig(
        netcfg_env,
        "prof_bad",
        namespaces=[
            _ns("bad_ns", interface="wlan1", phy="phy2").model_dump(mode="json")
        ],
    )
    faults = {
        ("bad_ns", ("ip", "link", "set", "wlan1", "up")): (
            "RTNETLINK answers: Operation not possible due to RF-kill\n"
        )
    }
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO, faults=faults) as inventory:
        assert nc.activate_config("prof_a", override_active=True) is True
        with pytest.raises(RunCommandError):
            nc.activate_config("prof_bad", override_active=True)
    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert inventory.live() == JOSH_LIVE
    assert not inventory.netns


def handle_deactivate_applies_default(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#271: after deactivate, radios match the default that current.txt names."""
    _write_netconfig(
        netcfg_env,
        "mon_cfg",
        roots=[
            _root(
                interface="wlan1", phy="phy2", mode=NetworkModeEnum.monitor
            ).model_dump(mode="json")
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        assert nc.activate_config("mon_cfg", override_active=True) is True
        assert inventory.live()["wlan1"] == ("phy2", None, "monitor")
        assert nc.deactivate_config("mon_cfg") is True
    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert inventory.live() == JOSH_LIVE


def handle_profile_skips_foreign_namespace_radio(
    namespace_service, netcfg_env, scenario: Scenario
):
    """Skip a radio in a namespace Core did not create; it is someone else's."""
    adapters = {
        **JOSH_THREE_RADIO,
        "wlan2": {**JOSH_THREE_RADIO["wlan2"], "netns": "user_ns"},
    }
    _write_netconfig(
        netcfg_env,
        "want_wlan2",
        roots=[_root(interface="wlan2", phy="phy1").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(adapters) as inventory:
        assert nc.activate_config("want_wlan2", override_active=True) is True
        assert nc.deactivate_config("want_wlan2") is True
    assert inventory.live()["wlan2"] == ("phy1", "user_ns", "managed")
    assert inventory.phy_moves == []
    assert inventory.netns == {"user_ns"}


def handle_atomic_write_failure_keeps_old_file(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#277: a failed write leaves the previous file intact and no temp files."""
    cfg = NetConfig(id="keep_me", namespaces=[], roots=[_root(interface="wlan0")])
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        assert nc.add_config(cfg) is True
        path = netcfg_env["cfg_dir"] / "keep_me.json"
        before = path.read_text()
        update = NetConfigUpdate(roots=[_root(interface="wlan1", phy="phy1")])
        with patch.object(nc.os, "replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                nc.edit_config("keep_me", update)
    assert path.read_text() == before
    assert not [
        f.name for f in netcfg_env["cfg_dir"].iterdir() if f.name.startswith(".")
    ]
    assert path.stat().st_mode & 0o777 == 0o600


def handle_force_delete_active_deactivates(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#277: deleting the active profile is refused, or with force deactivates it first."""
    _write_netconfig(
        netcfg_env,
        "active_cfg",
        namespaces=[_ns("ns_a", interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        assert nc.activate_config("active_cfg", override_active=True) is True
        with pytest.raises(ConfigActiveError):
            nc.delete_config("active_cfg")
        assert nc.delete_config("active_cfg", force=True) is True
    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert not (netcfg_env["cfg_dir"] / "active_cfg.json").exists()
    assert inventory.live() == JOSH_LIVE
    assert "ns_a" not in inventory.netns


def handle_monitor_restart_keeps_new_generation(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#279: a superseded monitor must not deregister the one that replaced it."""
    from wlanpi_core.connection import monitor as mon

    stop_all_connection_monitors()
    _wait_for_monitors_idle()
    cfg = _root(interface="wlan0", security=_security("SlowNet"))
    # Each generation's status poll blocks on its own event, so the test
    # decides when each one may move on.
    first_polling = threading.Event()
    release_first = threading.Event()
    second_polling = threading.Event()
    release_second = threading.Event()
    seen: list[threading.Thread] = []
    seen_lock = threading.Lock()

    def wpa_status(*args, **kwargs):
        me = threading.current_thread()
        with seen_lock:
            if me not in seen:
                seen.append(me)
            is_first = me is seen[0]
        if is_first:
            first_polling.set()
            assert release_first.wait(timeout=10), "first poll never released"
        else:
            second_polling.set()
            assert release_second.wait(timeout=10), "second poll never released"
        return {"wpa_status": {"wpa_state": "SCANNING"}}

    dhcp_threads: list[threading.Thread] = []

    def record_dhcp(*args, **kwargs):
        dhcp_threads.append(threading.current_thread())

    with patch("wlanpi_core.connection.monitor.get_wpa_status", side_effect=wpa_status):
        with patch(
            "wlanpi_core.connection.monitor.restart_dhcp_with_timeout",
            side_effect=record_dhcp,
        ):
            with _patch_monitor_clock():
                try:
                    ConnectionMonitor.start_monitor(cfg, "wlan0", None, timeout=15)
                    with mon._monitor_lock:
                        first = mon._connection_monitors["root:wlan0"]
                    assert first_polling.wait(timeout=5), "first monitor never polled"
                    assert seen[0] is first
                    # The first is blocked in its poll; replacing it signals it,
                    # waits (bounded), then registers the second.
                    ConnectionMonitor.start_monitor(cfg, "wlan0", None, timeout=15)
                    with mon._monitor_lock:
                        second = mon._connection_monitors["root:wlan0"]
                    assert second is not first
                    assert second_polling.wait(timeout=5), "second monitor never polled"
                    release_first.set()
                    first.join(timeout=5)
                    assert not first.is_alive(), "superseded monitor did not exit"
                    # The first has exited; the second must still be registered.
                    with mon._monitor_lock:
                        assert mon._connection_monitors.get("root:wlan0") is second
                finally:
                    release_first.set()
                    release_second.set()
                stop_all_connection_monitors()
                _wait_for_monitors_idle()
    # The superseded monitor must never reach DHCP; only the live one may.
    assert first not in dhcp_threads


def handle_monitor_stop_during_poll_skips_dhcp(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#279: a stop that lands while a poll is in flight must skip DHCP and the app."""
    from wlanpi_core.connection import monitor as mon

    stop_all_connection_monitors()
    _wait_for_monitors_idle()
    cfg = _root(interface="wlan0", security=_security("Net"), autostart_app="orb")
    polling = threading.Event()
    proceed = threading.Event()

    def wpa_status(*args, **kwargs):
        polling.set()
        assert proceed.wait(timeout=10), "test never released the status call"
        return {"wpa_status": {"wpa_state": "COMPLETED"}}

    with patch("wlanpi_core.connection.monitor.get_wpa_status", side_effect=wpa_status):
        with patch("wlanpi_core.connection.monitor.restart_dhcp_with_timeout") as dhcp:
            with patch(
                "wlanpi_core.namespaces.apps.start_app_in_namespace"
            ) as start_app:
                with _patch_monitor_clock():
                    ConnectionMonitor.start_monitor(cfg, "wlan0", None, timeout=15)
                    try:
                        assert polling.wait(timeout=5), "monitor never polled"
                        with mon._monitor_lock:
                            mon._monitor_stop_flags["root:wlan0"].set()
                    finally:
                        proceed.set()
                    _wait_for_monitors_idle()
    dhcp.assert_not_called()
    start_app.assert_not_called()


def handle_no_gatewayless_default_route(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#279: default_route on an interface with no gateway adds no route."""
    _write_netconfig(
        netcfg_env,
        "route_cfg",
        roots=[
            _root(interface="wlan1", phy="phy2", default_route=True).model_dump(
                mode="json"
            )
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        assert nc.activate_config("route_cfg", override_active=True) is True
    assert inventory.routes == []


def handle_display_name_does_not_capture_other_radio(
    namespace_service, netcfg_env, scenario: Scenario
):
    """Pick the radio by interface, not by a display name another radio carries."""
    _write_netconfig(
        netcfg_env,
        "clash_cfg",
        roots=[
            _root(interface="wlan2", phy="phy1", iface_display_name="wlan0").model_dump(
                mode="json"
            )
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        with pytest.raises(RunCommandError):
            nc.activate_config("clash_cfg", override_active=True)
    # wlan2 was picked (by interface), the rename clashed, and the failed
    # prepare touched only wlan2; the other radio's wlan0 is never deleted.
    assert inventory.deleted == [("wlan2", None)]
    assert ("wlan0", None) not in inventory.deleted
    assert inventory.live() == JOSH_LIVE
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


# --- P14: Core only touches what it created ---

OTHER_TOOLS_LAYOUT: dict[str, dict[str, str]] = {
    # wlanpi-profiler: hostapd holds wlan0 as AP, plus its own monitor
    "wlan0": {"phy": "phy0", "mac": "00:11:22:33:66:00", "type": "AP"},
    "wlan0profiler": {"phy": "phy0", "mac": "00:11:22:33:66:00", "type": "monitor"},
    "wlan1": {"phy": "phy1", "mac": "00:11:22:33:66:01"},
    # a user's own monitor interface
    "mon9": {"phy": "phy2", "mac": "00:11:22:33:66:02", "type": "monitor"},
    "wlan2": {"phy": "phy2", "mac": "00:11:22:33:66:02"},
}


def handle_default_leaves_other_tools_alone(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#202: the default never recreates interfaces Core did not create."""
    _write_netconfig(
        netcfg_env,
        "lab_cfg",
        namespaces=[_ns("ns_a", interface="wlan1", phy="phy1").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(OTHER_TOOLS_LAYOUT) as inventory:
        before = inventory.live()
        ok, outcomes = nc.activate_config_report("default", override_active=True)
        assert ok is True
        assert {o.status for o in outcomes} == {"skipped"}
        assert inventory.deleted == [] and inventory.adds == []
        # A profile cycle, which also records and tears down the default.
        assert nc.activate_config("lab_cfg", override_active=True) is True
        assert nc.deactivate_config("lab_cfg") is True
    after = inventory.live()
    for name in ("wlan0", "wlan0profiler", "mon9", "wlan2"):
        assert after[name] == before[name], name
    touched = {name for name, _ns in inventory.deleted}
    assert touched == {"wlan1"}


def handle_default_resets_core_created_netdev(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#202: the default still resets an interface Core itself created."""
    _write_netconfig(
        netcfg_env,
        "mon_cfg",
        roots=[
            _root(
                interface="wlan1", phy="phy2", mode=NetworkModeEnum.monitor
            ).model_dump(mode="json")
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        nc.get_config("default")  # snapshot the default while all are managed
        assert nc.activate_config("mon_cfg", override_active=True) is True
        # Core's record of the active profile is lost (e.g. current.txt reset).
        netcfg_env["ccf"].write_text("default")
        assert nc.activate_config("default", override_active=True) is True
    assert inventory.live() == JOSH_LIVE
    assert {name for name, _ns in inventory.deleted} == {"wlan1"}


def handle_deactivate_restores_renamed_root_entry(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#288: deactivating a root profile undoes its rename and mode."""
    _write_netconfig(
        netcfg_env,
        "lab_root",
        roots=[
            _root(
                interface="wlan1",
                iface_display_name="lab1",
                phy="phy2",
                mode=NetworkModeEnum.monitor,
            ).model_dump(mode="json")
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        assert nc.activate_config("lab_root", override_active=True) is True
        assert inventory.live()["lab1"] == ("phy2", None, "monitor")
        assert nc.deactivate_config("lab_root") is True
    assert inventory.live() == JOSH_LIVE
    assert {name for name, _ns in inventory.deleted} == {"wlan1", "lab1"}


def handle_revert_failure_is_reported(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#281: a revert step that fails is reported and the radio stays usable."""
    _write_netconfig(
        netcfg_env,
        "ns_cfg",
        namespaces=[_ns("ns_a", interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    # The kernel refuses both ways of addressing the phy.
    busy = "command failed: Busy (-16)\n"
    faults = {
        ("ns_a", ("iw", "phy#2", "set", "netns", "1")): busy,
        ("ns_a", ("iw", "phy", "phy2", "set", "netns", "1")): busy,
    }
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO, faults=faults) as inventory:
        assert nc.activate_config("ns_cfg", override_active=True) is True
        with pytest.raises(RunCommandError):
            nc.deactivate_config("ns_cfg")
    # The move back failed; wlan1 was recreated where it was, not left missing,
    # and the namespace holding it is kept.
    assert inventory.live()["wlan1"] == ("phy2", "ns_a", "managed")
    assert "ns_a" in inventory.netns
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_post_prepare_failure_rolls_back_entry(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#281: a failure after prepare (supplicant start) puts that entry back."""
    _write_netconfig(
        netcfg_env,
        "wpa_cfg",
        namespaces=[
            _ns(
                "ns_a", interface="wlan1", phy="phy2", security=_security("Net")
            ).model_dump(mode="json")
        ],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        with patch(
            "wlanpi_core.services.network_namespace_service.wpa_supplicant.start_or_restart_supplicant",
            side_effect=RunCommandError("wpa_supplicant failed to start", 1),
        ):
            with pytest.raises(RunCommandError):
                nc.activate_config("wpa_cfg", override_active=True)
    assert inventory.live() == JOSH_LIVE
    assert "ns_a" not in inventory.netns
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_marker_identity_guards_reused_name(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#284: a same-named namespace made later by another tool is not Core's."""
    _write_netconfig(
        netcfg_env,
        "ns_cfg",
        namespaces=[_ns("ns_a", interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        assert nc.activate_config("ns_cfg", override_active=True) is True
        # Out of band: ns_a is deleted (wlan1 returns to root), then another
        # tool creates its own ns_a and moves wlan2's radio into it.
        for cmd in (
            ["sudo", "ip", "netns", "delete", "ns_a"],
            ["sudo", "ip", "netns", "add", "ns_a"],
            ["sudo", "/sbin/iw", "phy#1", "set", "netns", "name", "ns_a"],
        ):
            inventory.run_command(cmd)
        assert nc.deactivate_config("ns_cfg") is True
    assert inventory.live()["wlan2"] == ("phy1", "ns_a", "managed")
    assert "ns_a" in inventory.netns


def handle_namespace_marker_kept_when_delete_fails(
    namespace_service, netcfg_env, scenario: Scenario
):
    """#284: if the namespace cannot be deleted, Core keeps its marker."""
    from wlanpi_core.services import network_namespace_service as nns

    _write_netconfig(
        netcfg_env,
        "ns_cfg",
        namespaces=[_ns("ns_a", interface="wlan1", phy="phy2").model_dump(mode="json")],
    )
    faults = {
        (
            None,
            ("ip", "netns", "delete", "ns_a"),
        ): "Cannot remove namespace file: Device or resource busy\n"
    }
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO, faults=faults) as inventory:
        assert nc.activate_config("ns_cfg", override_active=True) is True
        assert nc.deactivate_config("ns_cfg") is True
        assert nc.ns.core_namespaces() == ["ns_a"]
    assert inventory.live() == JOSH_LIVE
    assert (Path(nns.RUN_DIR) / "netns" / "ns_a").exists()


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
    "default_leaves_other_tools_alone": handle_default_leaves_other_tools_alone,
    "default_resets_core_created_netdev": handle_default_resets_core_created_netdev,
    "deactivate_restores_renamed_root_entry": handle_deactivate_restores_renamed_root_entry,
    "revert_failure_is_reported": handle_revert_failure_is_reported,
    "post_prepare_failure_rolls_back_entry": handle_post_prepare_failure_rolls_back_entry,
    "marker_identity_guards_reused_name": handle_marker_identity_guards_reused_name,
    "namespace_marker_kept_when_delete_fails": handle_namespace_marker_kept_when_delete_fails,
    "concurrent_activate_rejected": handle_concurrent_activate_rejected,
    "override_tears_down_previous": handle_override_tears_down_previous,
    "profile_skips_foreign_namespace_radio": handle_profile_skips_foreign_namespace_radio,
    "display_name_does_not_capture_other_radio": handle_display_name_does_not_capture_other_radio,
    "atomic_write_failure_keeps_old_file": handle_atomic_write_failure_keeps_old_file,
    "monitor_restart_keeps_new_generation": handle_monitor_restart_keeps_new_generation,
    "monitor_stop_during_poll_skips_dhcp": handle_monitor_stop_during_poll_skips_dhcp,
    "no_gatewayless_default_route": handle_no_gatewayless_default_route,
    "force_delete_active_deactivates": handle_force_delete_active_deactivates,
    "failed_override_falls_back_to_default": handle_failed_override_falls_back_to_default,
    "deactivate_applies_default": handle_deactivate_applies_default,
    "validate_duplicate_interface": handle_validate_duplicate_interface,
    "validate_display_name_shadows_interface": handle_validate_display_name_shadows_interface,
    "validate_same_name_other_namespace_ok": handle_validate_same_name_other_namespace_ok,
    "namespace_private_resolv_conf": handle_namespace_private_resolv_conf,
    "same_display_name_two_namespaces": handle_same_display_name_two_namespaces,
    "revert_leaves_foreign_namespace": handle_revert_leaves_foreign_namespace,
    "revert_moves_phy_without_netdev": handle_revert_moves_phy_without_netdev,
    "shared_phy_monitor_iface_round_trip": handle_shared_phy_monitor_iface_round_trip,
}


def run_scenario(scenario: Scenario, namespace_service, netcfg_env):
    handler = HANDLERS.get(scenario.name)
    if handler is None:
        pytest.fail(f"No handler registered for scenario {scenario.name}")
    handler(namespace_service, netcfg_env, scenario)
