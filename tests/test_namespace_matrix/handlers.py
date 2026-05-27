"""Scenario handlers for namespace_test_matrix.csv rows.

activate_config persist vs rollback paths: tests/scenarios/ACTIVATION_OUTCOMES.md
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wlanpi_core.connection.monitor import ConnectionMonitor, stop_all_connection_monitors
from wlanpi_core.models.network_config_errors import ConfigActiveError, ConfigMalformedError
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.schemas.network.network import (
    NetConfig,
    NetConfigUpdate,
    NamespaceConfig,
    NetworkModeEnum,
    NetSecurity,
    RootConfig,
    SecurityTypes,
)
from wlanpi_core.utils import network_config as nc
from tests.conftest import hardware_success_mocks, write_json_config
from tests.scenarios.loader import Scenario


def _security(ssid: str, psk: str | None = "secret") -> NetSecurity:
    return NetSecurity(ssid=ssid, security=SecurityTypes.wpa2, psk=psk)


def _root(**kwargs) -> RootConfig:
    base = dict(
        mode=NetworkModeEnum.managed,
        iface_display_name=kwargs.pop("iface_display_name", kwargs.get("interface", "wlan0")),
        phy=kwargs.pop("phy", "phy0"),
        interface=kwargs.pop("interface", "wlan0"),
        default_route=False,
        autostart_app=None,
        security=None,
        mlo=False,
    )
    base.update(kwargs)
    return RootConfig(**base)


def _ns(namespace: str, **kwargs) -> NamespaceConfig:
    root = _root(**kwargs)
    return NamespaceConfig(namespace=namespace, **root.model_dump())


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


def handle_validate_empty_iface_display_name(namespace_service, netcfg_env, scenario: Scenario):
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


def handle_validate_security_missing_ssid(namespace_service, netcfg_env, scenario: Scenario):
    cfg = RootConfig.model_construct(
        mode=NetworkModeEnum.managed,
        iface_display_name="wlan0",
        phy="phy0",
        interface="wlan0",
        default_route=False,
        autostart_app=None,
        mlo=False,
        security=NetSecurity.model_construct(ssid="", security=SecurityTypes.wpa2, psk="x"),
    )
    result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "security.ssid" in result.response.selectErr


def handle_validate_wpa2_missing_psk(namespace_service, netcfg_env, scenario: Scenario):
    cfg = _root(security=NetSecurity(ssid="MyNet", security=SecurityTypes.wpa2, psk=None))
    result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "security.psk is required" in result.response.selectErr


def handle_validate_invalid_security_type(namespace_service, netcfg_env, scenario: Scenario):
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
    result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "security.security must be one of" in result.response.selectErr


def handle_validate_autostart_app_empty_string(namespace_service, netcfg_env, scenario: Scenario):
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


def handle_validate_default_route_non_bool(namespace_service, netcfg_env, scenario: Scenario):
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
    result = namespace_service.activate_config(cfg)
    assert result.status == "error"
    assert "default_route must be a boolean" in result.response.selectErr


def handle_validate_netconfig_malformed_json(namespace_service, netcfg_env, scenario: Scenario):
    (netcfg_env["cfg_dir"] / "test_bad.json").write_text("{not valid json")
    with pytest.raises(ConfigMalformedError) as exc:
        nc.get_config("test_bad")
    assert exc.value.cfg_id == "test_bad"


def handle_validate_netconfig_empty_file(namespace_service, netcfg_env, scenario: Scenario):
    (netcfg_env["cfg_dir"] / "empty.json").write_text("")
    with pytest.raises(ConfigMalformedError) as exc:
        nc.get_config("empty")
    assert "empty" in exc.value.message.lower()


def handle_validate_netconfig_missing_id(namespace_service, netcfg_env, scenario: Scenario):
    (netcfg_env["cfg_dir"] / "no_id.json").write_text(json.dumps({"namespaces": [], "roots": []}))
    with pytest.raises(ConfigMalformedError):
        nc.get_config("no_id")


def handle_validate_netconfig_invalid_root_shape(namespace_service, netcfg_env, scenario: Scenario):
    (netcfg_env["cfg_dir"] / "bad_root.json").write_text(
        json.dumps({"id": "bad_root", "namespaces": [], "roots": [{"interface": "wlan0"}]})
    )
    with pytest.raises(ConfigMalformedError):
        nc.get_config("bad_root")


def handle_user_edit_active_config_blocked(namespace_service, netcfg_env, scenario: Scenario):
    write_json_config(
        netcfg_env["cfg_dir"],
        "ns_cfg",
        {"id": "ns_cfg", "namespaces": [], "roots": [_root().model_dump(mode="json")]},
    )
    netcfg_env["ccf"].write_text("ns_cfg")
    with pytest.raises(ConfigActiveError):
        nc.edit_config("ns_cfg", NetConfigUpdate(roots=[]))


# --- filesystem / recovery config ---


def handle_files_current_points_to_deleted(namespace_service, netcfg_env, scenario: Scenario):
    netcfg_env["ccf"].write_text("ghost_cfg")
    with pytest.raises(ConfigMalformedError) as exc:
        nc.recover_current_config()
    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert "invalid or malformed" in exc.value.message.lower()


def handle_list_configs_malformed_annotation(namespace_service, netcfg_env, scenario: Scenario):
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
    cfg = nc.get_default_config()
    loaded = nc.get_config("default")
    assert loaded.id == cfg.id
    assert (netcfg_env["cfg_dir"] / "default.json").exists()


def handle_default_hardcoded_no_file(namespace_service, netcfg_env, scenario: Scenario):
    assert not (netcfg_env["cfg_dir"] / "default.json").exists()
    from wlanpi_core.schemas.network.network import NetworkSetupLog, NetworkSetupStatus

    ok_status = NetworkSetupStatus(
        status="provisioned",
        response=NetworkSetupLog(selectErr="", eventLog=[]),
        connectedNet=None,
        input="",
    )
    with patch.object(nc.ns, "activate_config", return_value=ok_status):
        assert nc.activate_config("default", override_active=True) is True
    assert netcfg_env["ccf"].read_text().strip() == "default"


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
    hardcoded = nc.get_default_config()
    assert loaded.model_dump() != hardcoded.model_dump()


def handle_default_startup_malformed_current(namespace_service, netcfg_env, scenario: Scenario):
    netcfg_env["ccf"].write_text("")
    write_json_config(
        netcfg_env["cfg_dir"],
        "default",
        nc.get_default_config().model_dump(mode="json"),
    )
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


def handle_adapter_interface_not_in_iw_list(namespace_service, netcfg_env, scenario: Scenario):
    roots = [
        _root(interface="wlan9", phy="phy0").model_dump(mode="json"),
        _root(interface="wlan1", phy="phy1", iface_display_name="wlan1").model_dump(mode="json"),
    ]
    _write_netconfig(netcfg_env, "missing_iface_cfg", roots=roots)
    with hardware_success_mocks(interfaces=["wlan1"]):
        assert nc.activate_config("missing_iface_cfg", override_active=True) is True


def handle_adapter_phy_declared_not_present(namespace_service, netcfg_env, scenario: Scenario):
    _write_netconfig(
        netcfg_env,
        "stale_phy_cfg",
        namespaces=[_ns("stale_ns", interface="wlan2", phy="phy3").model_dump(mode="json")],
        roots=[_root().model_dump(mode="json")],
    )
    with hardware_success_mocks(interfaces=["wlan0"]):
        assert nc.activate_config("stale_phy_cfg", override_active=True) is True


def handle_multi_adapter_one_unplugged_later_ok(namespace_service, netcfg_env, scenario: Scenario):
    _write_netconfig(
        netcfg_env,
        "triple_cfg",
        namespaces=[_ns("ns_b", interface="wlan1", phy="phy1").model_dump(mode="json")],
        roots=[
            _root(security=_security("wlan0")).model_dump(mode="json"),
            _root(interface="wlan2", phy="phy2", iface_display_name="wlan2").model_dump(mode="json"),
        ],
    )
    with hardware_success_mocks(interfaces=["wlan0", "wlan1"]):
        assert nc.activate_config("triple_cfg", override_active=True) is True
    assert netcfg_env["ccf"].read_text().strip() == "triple_cfg"


def handle_multi_adapter_one_unplugged_plus_ns_ok(namespace_service, netcfg_env, scenario: Scenario):
    _write_netconfig(
        netcfg_env,
        "mixed_cfg",
        namespaces=[
            _ns("scan_ns", interface="wlan0", phy="phy0", mode=NetworkModeEnum.monitor).model_dump(
                mode="json"
            )
        ],
        roots=[_root(interface="wlan2", phy="phy2", iface_display_name="wlan2").model_dump(mode="json")],
    )
    with hardware_success_mocks(interfaces=["wlan0"]):
        assert nc.activate_config("mixed_cfg", override_active=True) is True


def handle_multi_adapter_phy_fault_unacceptable(namespace_service, netcfg_env, scenario: Scenario):
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


def handle_partial_activation_rollback(namespace_service, netcfg_env, scenario: Scenario):
    def fail_phy9(phy_name, namespace):
        if phy_name == "phy9":
            raise RunCommandError("missing phy", 1)

    _write_netconfig(
        netcfg_env,
        "bad_cfg",
        namespaces=[
            _ns("good_ns", interface="wlan0", phy="phy0").model_dump(mode="json"),
            _ns("bad_ns", interface="wlan1", phy="phy9").model_dump(mode="json"),
        ],
    )
    deactivate_calls = []

    def track_deactivate(cfg):
        deactivate_calls.append(cfg.interface)

    with hardware_success_mocks(phy_move_side_effect=fail_phy9):
        with patch.object(nc.ns, "deactivate_config", side_effect=track_deactivate):
            assert nc.activate_config("bad_cfg", override_active=True) is False
    assert netcfg_env["ccf"].read_text().strip() == "default"
    assert "wlan0" in deactivate_calls


def handle_activation_exception_mid_loop_rollback(namespace_service, netcfg_env, scenario: Scenario):
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


def handle_deactivate_exception_mid_loop_rollback(namespace_service, netcfg_env, scenario: Scenario):
    """deactivate_config: ccf=default and revert_to_root still run before re-raise on mid-loop failure."""

    _write_netconfig(
        netcfg_env,
        "dual_ns_cfg",
        namespaces=[
            _ns("ns_a", interface="wlan0", phy="phy0").model_dump(mode="json"),
            _ns("ns_b", interface="wlan1", phy="phy1", iface_display_name="wlan1").model_dump(
                mode="json"
            ),
        ],
    )
    netcfg_env["ccf"].write_text("dual_ns_cfg")
    revert_calls = []

    def deactivate_side_effect(cfg):
        if cfg.interface == "wlan1":
            raise RunCommandError("deactivate failed", 1)

    with patch.object(nc.ns, "deactivate_config", side_effect=deactivate_side_effect):
        with patch.object(nc.ns, "revert_to_root", side_effect=lambda *a, **k: revert_calls.append(True)):
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
            _ns("ns_b", interface="wlan1", phy="phy1", iface_display_name="wlan1").model_dump(mode="json"),
        ],
    )
    with hardware_success_mocks():
        assert nc.activate_config("split_cfg", override_active=True) is True
    assert netcfg_env["ccf"].read_text().strip() == "split_cfg"


def handle_move_wlan1_to_ns_orb_no_security(namespace_service, netcfg_env, scenario: Scenario):
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


def handle_user_manual_namespace_exists(namespace_service, netcfg_env, scenario: Scenario):
    cfg = _ns("my_ns", interface="wlan1", phy="phy1", iface_display_name="wlan1")
    with hardware_success_mocks():
        with patch(
            "wlanpi_core.services.network_namespace_service.ns_namespace.namespace_exists",
            return_value=True,
        ) as exists:
            with patch(
                "wlanpi_core.services.network_namespace_service.ns_namespace.create_namespace",
            ) as create_ns:
                assert namespace_service._prepare_namespace(cfg) is True
                exists.assert_called_once_with("my_ns")
                create_ns.assert_not_called()


def handle_ssid_prestage_immediate_provisioned(namespace_service, netcfg_env, scenario: Scenario):
    cfg = _root(security=_security("HiddenNet"))
    with hardware_success_mocks():
        with patch.object(namespace_service, "_monitor_connection_async") as monitor:
            result = namespace_service.activate_config(cfg)
            monitor.assert_called_once()
    assert result.status == "provisioned"


def handle_ssid_delayed_multi_adapter_no_fault(namespace_service, netcfg_env, scenario: Scenario):
    _write_netconfig(
        netcfg_env,
        "dual_prestage_cfg",
        namespaces=[
            _ns("ns_a", interface="wlan0", phy="phy0", security=_security("LateNet")).model_dump(mode="json"),
            _ns("ns_b", interface="wlan1", phy="phy1", iface_display_name="wlan1", mode=NetworkModeEnum.monitor).model_dump(
                mode="json"
            ),
        ],
    )
    with hardware_success_mocks():
        assert nc.activate_config("dual_prestage_cfg", override_active=True) is True


def handle_default_return_via_deactivate(namespace_service, netcfg_env, scenario: Scenario):
    _write_netconfig(
        netcfg_env,
        "custom_ns_cfg",
        namespaces=[_ns("test_ns", interface="wlan0", phy="phy0", security=_security("test")).model_dump(mode="json")],
        roots=[_root(interface="wlan1", phy="phy1", iface_display_name="wlan1").model_dump(mode="json")],
    )
    netcfg_env["ccf"].write_text("custom_ns_cfg")
    with hardware_success_mocks():
        with patch.object(nc.ns, "revert_to_root") as revert:
            assert nc.deactivate_config("custom_ns_cfg", override_active=True) is True
            revert.assert_any_call(None)
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_user_broken_active_override_deactivate(namespace_service, netcfg_env, scenario: Scenario):
    _write_netconfig(
        netcfg_env,
        "broken_cfg",
        namespaces=[_ns("orphan_ns", interface="wlan0", phy="phy0").model_dump(mode="json")],
    )
    netcfg_env["ccf"].write_text("broken_cfg")
    with patch.object(nc.ns, "deactivate_config"):
        with patch.object(nc.ns, "revert_to_root") as revert:
            assert nc.deactivate_config("broken_cfg", override_active=True) is True
            revert.assert_any_call(None)
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_user_manual_phy_move_then_recover(namespace_service, netcfg_env, scenario: Scenario):
    _write_netconfig(
        netcfg_env,
        "ns_cfg",
        namespaces=[_ns("my_ns", interface="wlan0", phy="phy0").model_dump(mode="json")],
    )
    netcfg_env["ccf"].write_text("ns_cfg")
    with patch.object(nc.ns, "deactivate_config"):
        with patch.object(nc.ns, "revert_to_root") as revert:
            assert nc.deactivate_config("ns_cfg", override_active=True) is True
            revert.assert_any_call(None)


# --- connection monitor ---


def _wait_for_monitors_idle(timeout_seconds: float = 3.0) -> None:
    import time
    from wlanpi_core.connection import monitor as mon

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with mon._monitor_lock:
            if not mon._connection_monitors:
                return
        time.sleep(0.05)


def handle_ssid_delayed_connect_within_monitor(namespace_service, netcfg_env, scenario: Scenario):
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

    def wpa_side_effect():
        pending = iter(status_sequence)
        for item in pending:
            yield item
        while True:
            yield {"wpa_status": {"wpa_state": "COMPLETED"}}

    with patch("wlanpi_core.connection.monitor.get_wpa_status", side_effect=wpa_side_effect()):
        with patch("wlanpi_core.connection.monitor.restart_dhcp_with_timeout") as dhcp:
            with patch("wlanpi_core.connection.monitor.set_default_route"):
                with patch("wlanpi_core.namespaces.apps.start_app_in_namespace") as start_app:
                    ConnectionMonitor.start_monitor(cfg, "wlan0", "ns_a", timeout=5)
                    import time

                    deadline = time.time() + 6
                    while time.time() < deadline and not dhcp.called:
                        time.sleep(0.05)
                    stop_all_connection_monitors()
                    _wait_for_monitors_idle()
    dhcp.assert_called_once()
    start_app.assert_called_once_with("ns_a", "orb")


def handle_ssid_delayed_beyond_monitor_timeout(namespace_service, netcfg_env, scenario: Scenario):
    stop_all_connection_monitors()
    cfg = _root(
        security=_security("VeryLateNet"),
        autostart_app="orb",
    )
    with patch(
        "wlanpi_core.connection.monitor.get_wpa_status",
        return_value={"wpa_status": {"wpa_state": "SCANNING"}},
    ):
        with patch("wlanpi_core.connection.monitor.restart_dhcp_with_timeout") as dhcp:
            with patch("wlanpi_core.namespaces.apps.start_app_in_namespace") as start_app:
                with patch("wlanpi_core.connection.monitor.time.sleep"):
                    ConnectionMonitor.start_monitor(cfg, "wlan0", None, timeout=15)
                    import time

                    time.sleep(0.1)
                    stop_all_connection_monitors()
                    _wait_for_monitors_idle()
    dhcp.assert_not_called()
    start_app.assert_not_called()


def handle_move_wlan1_to_ns_with_orb_monitor(namespace_service, netcfg_env, scenario: Scenario):
    _write_netconfig(
        netcfg_env,
        "ns_orb_cfg",
        namespaces=[
            _ns("orb_ns", interface="wlan1", phy="phy1", iface_display_name="wlan1", security=_security("orbnet")).model_dump(
                mode="json"
            )
        ],
        roots=[_root(security=_security("rootnet")).model_dump(mode="json")],
    )
    with hardware_success_mocks():
        with patch.object(nc.ns, "_monitor_connection_async") as monitor:
            assert nc.activate_config("ns_orb_cfg", override_active=True) is True
            assert monitor.call_count >= 1


def handle_files_apps_json_missing_orb(namespace_service, netcfg_env, scenario: Scenario):
    stop_all_connection_monitors()
    cfg = _ns("orb_ns", interface="wlan1", phy="phy1", iface_display_name="wlan1", autostart_app="orb")
    with patch(
        "wlanpi_core.connection.monitor.get_wpa_status",
        return_value={"wpa_status": {"wpa_state": "COMPLETED"}},
    ):
        with patch("wlanpi_core.connection.monitor.restart_dhcp_with_timeout"):
            with patch("wlanpi_core.namespaces.apps.get_app_command", return_value=None):
                with patch("wlanpi_core.namespaces.apps.start_app_in_namespace") as start_app:
                    with patch("wlanpi_core.connection.monitor.time.sleep"):
                        ConnectionMonitor.start_monitor(cfg, "wlan1", "orb_ns", timeout=5)
                        import time

                        time.sleep(0.1)
                        stop_all_connection_monitors()
                        _wait_for_monitors_idle()
    start_app.assert_not_called()


HANDLERS = {
    "default_hardcoded_no_file": handle_default_hardcoded_no_file,
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
}


def run_scenario(scenario: Scenario, namespace_service, netcfg_env):
    handler = HANDLERS.get(scenario.name)
    if handler is None:
        pytest.fail(f"No handler registered for scenario {scenario.name}")
    handler(namespace_service, netcfg_env, scenario)
