from __future__ import annotations

import subprocess
import threading
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.test_route_auth_guard import _api_routes
from wlanpi_core.api.api_v1.endpoints import (
    network_config_api,
    profiler_api,
    system_api,
)
from wlanpi_core.app import create_app
from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.core.config import settings
from wlanpi_core.core.transmit_gate import (
    require_transmit,
    require_transmit_for_power,
    require_transmit_for_unit,
)
from wlanpi_core.core.transmit_policy import (
    GO_DETAIL,
    TRANSMIT_UNITS,
    UNKNOWN_DETAIL,
    refusal_detail,
)
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.network.network import NetConfig
from wlanpi_core.services import bluetooth_service, platform_cache, system_service
from wlanpi_core.services.platform_cache import (
    boot_model,
    cached_model,
    load_platform_cache,
    resolve_model,
)
from wlanpi_core.utils import network_config

_TRANSMIT_DEPENDENCIES = {
    require_transmit,
    require_transmit_for_unit,
    require_transmit_for_power,
}

_GATED_ROUTES = {
    ("POST", "/api/v1/bluetooth/pair"): require_transmit,
    ("POST", "/api/v1/system/service/start"): require_transmit_for_unit,
    ("POST", "/api/v1/system/service/restart"): require_transmit_for_unit,
    ("POST", "/api/v1/bluetooth/power/{action}"): require_transmit_for_power,
}

_UNGATED_ROUTES = (
    ("POST", "/api/v1/profiler/start"),
    ("POST", "/api/v1/profiler/stop"),
    ("POST", "/api/v1/profiler/purge"),
    ("POST", "/api/v1/system/reg-domain/set"),
    ("POST", "/api/v1/system/service/stop"),
    ("POST", "/api/v1/network/config/deactivate/{id}"),
    ("POST", "/api/v1/network/config/reset"),
    ("DELETE", "/api/v1/network/config/{id}"),
    ("POST", "/api/v1/network/wlan/revert"),
    ("GET", "/api/v1/bluetooth/status"),
    ("GET", "/api/v1/utils/wlan/scan"),
    ("GET", "/api/v1/network/wlan/scan"),
    ("POST", "/api/v1/system/reboot"),
    ("POST", "/api/v1/system/shutdown"),
    ("POST", "/api/v1/utils/blinker/start"),
    ("POST", "/api/v1/network/interfaces/{iface}/renew"),
    ("POST", "/api/v1/network/ethernet/{interface}/vlan/{vlan}"),
)

_IGNORED_METHODS = {"HEAD", "OPTIONS"}

_BLUETOOTH_STATUS = {
    "name": "wlanpi",
    "alias": "wlanpi",
    "addr": "00:00:00:00:00:00",
    "power": "Off",
    "blocked": False,
    "paired_devices": [],
}


def _timeout() -> subprocess.TimeoutExpired:
    return subprocess.TimeoutExpired(["wlanpi-model", "-b"], 30)


def _plant(value: str | subprocess.TimeoutExpired | None) -> None:
    platform_cache._cached = value


def _probe_returns(mocker, *results: str | Exception):
    return mocker.patch(
        "wlanpi_core.services.system_service.get_platform", side_effect=list(results)
    )


def _entry(**fields: object) -> dict[str, object]:
    return {
        "iface_display_name": "wlan0",
        "phy": "phy0",
        "interface": "wlan0",
        **fields,
    }


_MONITOR_ONLY = NetConfig.model_validate(
    {"id": "mon", "roots": [_entry(mode="monitor")]}
)
_WITH_SECURITY = NetConfig.model_validate(
    {"id": "lab_cfg", "roots": [_entry(security={"ssid": "lab", "security": "OPEN"})]}
)
_WITH_APP = NetConfig.model_validate(
    {"id": "app", "namespaces": [_entry(namespace="ns1", autostart_app="orb")]}
)


@pytest.fixture
def radios(netcfg_env, mocker):
    mocker.patch.object(network_config, "_invalid_entries", return_value=[])
    return {
        "apply": mocker.patch.object(network_config, "_apply_entries", return_value=[]),
        "teardown": mocker.patch.object(network_config, "_teardown_profile"),
        "ccf": netcfg_env["ccf"],
    }


def _stored(mocker, *configs: NetConfig):
    versions: dict[str, list[NetConfig]] = {}
    for cfg in configs:
        versions.setdefault(cfg.id, []).append(cfg)

    def get_config(cfg_id: str) -> NetConfig:
        found = versions.get(cfg_id) or [NetConfig(id=cfg_id)]
        return found.pop(0) if len(found) > 1 else found[0]

    return mocker.patch.object(network_config, "get_config", side_effect=get_config)


@pytest.fixture
def client():
    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(verify_auth_wrapper, None)


@pytest.mark.parametrize(
    ("value", "detail"),
    [
        ("Go", GO_DETAIL),
        ("Unknown", UNKNOWN_DETAIL),
        ("M4", None),
        ("M4+", None),
        ("R4", None),
        ("Pro", None),
        ("R5", None),
        ("go", GO_DETAIL),
        ("Go2", GO_DETAIL),
        ("Unknown platform", UNKNOWN_DETAIL),
    ],
)
def test_refusal_detail(value: str, detail: str | None):
    assert refusal_detail(value) == detail


def test_transmit_units_are_allowlisted():
    assert TRANSMIT_UNITS <= set(system_service.allowed_services)


def _dependency_calls(route: APIRoute) -> list[object]:
    return [dependency.call for dependency in route.dependant.dependencies]


def _find_route(routes: list[tuple[str, APIRoute]], method: str, path: str) -> APIRoute:
    found = [
        route
        for route_path, route in routes
        if route_path == path and method in route.methods
    ]
    assert len(found) == 1, f"{method} {path} matched {len(found)}"
    return found[0]


def test_transmit_dependencies_match_the_route_table():
    routes = list(_api_routes())

    for (method, path), dependency in _GATED_ROUTES.items():
        assert dependency in _dependency_calls(_find_route(routes, method, path))

    for method, path in _UNGATED_ROUTES:
        calls = set(_dependency_calls(_find_route(routes, method, path)))
        assert not calls & _TRANSMIT_DEPENDENCIES

    offenders: list[tuple[str, str]] = []
    gated = set(_GATED_ROUTES)
    for path, route in routes:
        if not set(_dependency_calls(route)) & _TRANSMIT_DEPENDENCIES:
            continue
        for method in route.methods:
            if method in _IGNORED_METHODS:
                continue
            if (method, path) not in gated:
                offenders.append((method, path))
    assert offenders == []


@pytest.mark.parametrize("planted", ["Go", "Unknown", "", _timeout()])
def test_profiler_start_reaches_downstream_including_no_ap(client, mocker, planted):
    _plant(planted)
    start = mocker.patch.object(
        profiler_api.cli,
        "start_profiler",
        new=AsyncMock(return_value={"success": True}),
    )

    response = client.post("/api/v1/profiler/start", json={"noAP": True})

    assert response.status_code == 200
    start.assert_awaited()


def test_reg_domain_set_on_go_reaches_downstream(client, mocker):
    _plant("Go")
    set_domain = mocker.patch.object(
        system_api.system_service,
        "set_reg_domain",
        return_value={"country": "US", "source": "wlanpi-reg-domain", "raw": "US"},
    )

    response = client.post("/api/v1/system/reg-domain/set", json={"country": "US"})

    assert response.status_code == 200
    set_domain.assert_called_once_with("US")


@pytest.mark.parametrize("model", ["M4", "M4+", "R4", "Pro"])
def test_profiler_start_allowed_models_reach_downstream(client, mocker, model: str):
    _plant(model)
    start = mocker.patch.object(
        profiler_api.cli,
        "start_profiler",
        new=AsyncMock(return_value={"success": True}),
    )

    response = client.post("/api/v1/profiler/start", json={"noAP": True})

    assert response.status_code == 200
    start.assert_awaited()


def test_profiler_start_without_auth_is_401_not_transmit_detail():
    _plant("Go")

    with TestClient(app) as raw_client:
        response = raw_client.post("/api/v1/profiler/start", json={"noAP": True})

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication required: Bearer token or request signature"
    }


def test_bluetooth_status_on_go_is_not_403(client, mocker):
    _plant("Go")
    mocker.patch.object(
        bluetooth_service,
        "bluetooth_status",
        return_value=_BLUETOOTH_STATUS,
    )

    response = client.get("/api/v1/bluetooth/status")

    assert response.status_code == 200


def test_service_start_cockpit_on_go_reaches_downstream(client, mocker):
    _plant("Go")
    start = mocker.patch.object(
        system_api.system_service,
        "start_systemd_service",
        new=AsyncMock(return_value={"name": "cockpit", "active": True}),
    )

    response = client.post("/api/v1/system/service/start", params={"name": "cockpit"})

    assert response.status_code == 200
    start.assert_awaited_once_with("cockpit")


@pytest.mark.parametrize("action", ["start", "restart"])
def test_wlanpi_profiler_service_on_go_reaches_downstream(client, mocker, action: str):
    _plant("Go")
    method = "start_systemd_service" if action == "start" else "restart_systemd_service"
    called = mocker.patch.object(
        system_api.system_service,
        method,
        new=AsyncMock(return_value={"name": "wlanpi-profiler", "active": True}),
    )

    response = client.post(
        f"/api/v1/system/service/{action}",
        params={"name": "wlanpi-profiler"},
    )

    assert response.status_code == 200
    called.assert_awaited_once_with("wlanpi-profiler")


@pytest.mark.parametrize("name", ["hostapd", "Hostapd.service"])
def test_service_start_transmit_unit_on_go_is_403(client, mocker, name: str):
    _plant("Go")
    start = mocker.patch.object(
        system_api.system_service,
        "start_systemd_service",
        new=AsyncMock(return_value={"name": name, "active": True}),
    )

    response = client.post("/api/v1/system/service/start", params={"name": name})

    assert response.status_code == 403
    assert response.json() == {"detail": GO_DETAIL}
    start.assert_not_awaited()


def test_bluetooth_power_off_on_go_is_not_403(client, mocker):
    _plant("Go")
    mocker.patch.object(bluetooth_service, "bluetooth_adapter", return_value="hci0")
    mocker.patch.object(bluetooth_service, "bluetooth_present", return_value=True)
    set_power = mocker.patch.object(
        bluetooth_service, "bluetooth_set_power", return_value=True
    )

    response = client.post("/api/v1/bluetooth/power/off")

    assert response.status_code == 200
    set_power.assert_called_once_with(False, "hci0")


def test_bluetooth_power_on_on_go_is_403(client, mocker):
    _plant("Go")
    set_power = mocker.patch.object(
        bluetooth_service, "bluetooth_set_power", return_value=True
    )

    response = client.post("/api/v1/bluetooth/power/on")

    assert response.status_code == 403
    assert response.json() == {"detail": GO_DETAIL}
    set_power.assert_not_called()


def test_bluetooth_power_banana_on_go_is_plain_text_400(client, mocker):
    _plant("Go")
    set_power = mocker.patch.object(
        bluetooth_service, "bluetooth_set_power", return_value=True
    )

    response = client.post("/api/v1/bluetooth/power/banana")

    assert response.status_code == 400
    assert response.text == "Invalid action. Use 'on' or 'off'."
    set_power.assert_not_called()


def test_activate_manual_on_m4_is_409(client, mocker, monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "manual")
    _plant("M4")
    activate = mocker.patch.object(
        network_config_api.network_config, "activate_config_report"
    )

    response = client.post("/api/v1/network/config/activate/lab_cfg")

    assert response.status_code == 409
    assert "WLAN_MANAGEMENT=manual" in response.json()["detail"]
    activate.assert_not_called()


def test_activate_go_manual_is_409_before_transmit_refusal(client, mocker, monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "manual")
    _plant("Go")
    activate = mocker.patch.object(
        network_config_api.network_config, "activate_config_report"
    )

    response = client.post("/api/v1/network/config/activate/lab_cfg")

    assert response.status_code == 409
    assert "WLAN_MANAGEMENT=manual" in response.json()["detail"]
    activate.assert_not_called()


def _refuse_service(client, mocker, name: str, action: str = "start"):
    method = "start_systemd_service" if action == "start" else "restart_systemd_service"
    called = mocker.patch.object(
        system_api.system_service,
        method,
        new=AsyncMock(return_value={"name": name, "active": True}),
    )
    response = client.post(
        f"/api/v1/system/service/{action}",
        params={"name": name},
    )
    return response, called


@pytest.mark.parametrize(
    ("action", "name"),
    [
        ("restart", "hostapd"),
        ("start", "wpa_supplicant@wlan0"),
        ("start", "bt-agent"),
        ("start", "bt-network"),
    ],
)
def test_transmit_units_on_go_are_403(client, mocker, action: str, name: str):
    _plant("Go")

    response, called = _refuse_service(client, mocker, name, action)

    assert response.status_code == 403
    assert response.json() == {"detail": GO_DETAIL}
    called.assert_not_awaited()


_UNTRUSTED = ("Unknown platform", "Unknown", _timeout())


@pytest.mark.parametrize("result", _UNTRUSTED)
def test_hostapd_start_untrusted_is_403(client, mocker, result):
    _plant(result)
    _probe_returns(mocker, result)

    response, called = _refuse_service(client, mocker, "hostapd")

    assert response.status_code == 403
    assert response.json() == {"detail": UNKNOWN_DETAIL}
    called.assert_not_awaited()


@pytest.mark.parametrize("result", _UNTRUSTED)
def test_bluetooth_power_on_untrusted_is_403(client, mocker, result):
    _plant(result)
    _probe_returns(mocker, result)
    set_power = mocker.patch.object(
        bluetooth_service, "bluetooth_set_power", return_value=True
    )

    response = client.post("/api/v1/bluetooth/power/on")

    assert response.status_code == 403
    assert response.json() == {"detail": UNKNOWN_DETAIL}
    set_power.assert_not_called()


@pytest.mark.parametrize(
    ("planted", "detail"),
    [("Go", GO_DETAIL), *((result, UNKNOWN_DETAIL) for result in _UNTRUSTED)],
)
@pytest.mark.parametrize("cfg", [_WITH_SECURITY, _WITH_APP])
def test_activate_transmitting_config_is_403(
    client, mocker, monkeypatch, radios, cfg, planted, detail
):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "auto")
    _plant(planted)
    _probe_returns(mocker, planted)
    _stored(mocker, cfg)

    response = client.post(f"/api/v1/network/config/activate/{cfg.id}")

    assert response.status_code == 403
    assert response.json() == {"detail": detail}
    radios["apply"].assert_not_called()
    radios["teardown"].assert_not_called()
    assert radios["ccf"].read_text() == "default"


@pytest.mark.parametrize("planted", ["Go", "Unknown platform"])
def test_activate_monitor_only_config_reaches_downstream(
    client, mocker, monkeypatch, radios, planted
):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "auto")
    _plant(planted)
    _stored(mocker, _MONITOR_ONLY)

    response = client.post("/api/v1/network/config/activate/mon")

    assert response.status_code == 200
    radios["apply"].assert_called_once()
    assert radios["ccf"].read_text() == "mon"


def test_activate_applies_the_config_it_checked(client, mocker, monkeypatch, radios):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "auto")
    _plant("Go")
    edited = _WITH_SECURITY.model_copy(update={"id": "mon"})
    get_config = _stored(mocker, _MONITOR_ONLY, edited)

    response = client.post("/api/v1/network/config/activate/mon")

    assert response.status_code == 200
    assert [c.args for c in get_config.call_args_list].count(("mon",)) == 1
    assert radios["apply"].call_args.args[0] is _MONITOR_ONLY


def test_activate_transmitting_config_on_allowed_model_reaches_downstream(
    client, mocker, monkeypatch, radios
):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "auto")
    _stored(mocker, _WITH_SECURITY)

    response = client.post("/api/v1/network/config/activate/lab_cfg")

    assert response.status_code == 200
    radios["apply"].assert_called_once()


def test_restoring_transmitting_profile_on_go_falls_back_to_default(mocker, radios):
    _plant("Go")
    radios["ccf"].write_text("lab_cfg")
    _stored(mocker, _WITH_SECURITY)

    with pytest.raises(ValidationError) as caught:
        network_config.activate_config("lab_cfg", override_active=True)

    assert caught.value.status_code == 403
    radios["teardown"].assert_called_once_with("lab_cfg")
    radios["apply"].assert_not_called()
    assert radios["ccf"].read_text() == "default"


def test_activate_missing_config_is_404_not_403(client, monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "auto")
    _plant("Go")

    response = client.post("/api/v1/network/config/activate/no_such_cfg")

    assert response.status_code == 404


@pytest.mark.parametrize("model", ["Go", "M4+", "R4", "R5", "Pro"])
def test_final_model_is_not_probed_again(mocker, model: str):
    _plant(model)
    probe = _probe_returns(mocker)

    assert resolve_model() == model
    probe.assert_not_called()


@pytest.mark.parametrize(
    ("second", "expected"), [("M4", "M4"), (_timeout(), "Unknown")]
)
def test_m4_is_probed_again_on_every_gated_call(mocker, second, expected):
    _plant("M4")
    probe = _probe_returns(mocker, second, "M4")

    assert resolve_model() == expected
    assert resolve_model() == "M4"
    assert probe.call_count == 2


@pytest.mark.parametrize(
    ("second", "expected"), [("Go", "Go"), ("M4", "M4"), (_timeout(), "Unknown")]
)
def test_cold_m4_is_probed_twice(mocker, second, expected):
    _plant(None)
    probe = _probe_returns(mocker, "M4", second)

    assert resolve_model() == expected
    assert probe.call_count == 2


def test_cold_final_model_is_probed_once(mocker):
    _plant(None)
    probe = _probe_returns(mocker, "Pro")

    assert resolve_model() == "Pro"
    probe.assert_called_once()


def test_cold_m4_on_go_refuses_hostapd(client, mocker):
    _plant(None)
    _probe_returns(mocker, "M4", "Go")

    response, called = _refuse_service(client, mocker, "hostapd")

    assert response.status_code == 403
    assert response.json() == {"detail": GO_DETAIL}
    called.assert_not_awaited()


def test_m4_that_probes_as_go_stays_go(mocker):
    _plant("M4")
    probe = _probe_returns(mocker, "Go")

    assert resolve_model() == "Go"
    assert resolve_model() == "Go"
    probe.assert_called_once()


@pytest.mark.parametrize("first", ["Unknown platform", "", _timeout()])
def test_untrusted_result_is_probed_again(mocker, first):
    _plant(first)
    _probe_returns(mocker, "Pro")

    assert resolve_model() == "Pro"


def test_concurrent_gated_calls_share_one_probe(mocker, monkeypatch):
    _plant("M4")
    release = threading.Event()
    second_waiting = threading.Event()
    real_lock = threading.Lock()
    count_lock = threading.Lock()
    entries = {"n": 0}

    class _CountingLock:
        def __enter__(self) -> None:
            with count_lock:
                entries["n"] += 1
                if entries["n"] == 2:
                    second_waiting.set()
            real_lock.acquire()

        def __exit__(self, *exc: object) -> None:
            real_lock.release()

    monkeypatch.setattr(platform_cache, "_lock", _CountingLock())

    def slow_probe() -> str:
        if not release.wait(timeout=2):
            raise AssertionError("probe was not released")
        return "M4"

    probe = mocker.patch(
        "wlanpi_core.services.system_service.get_platform", side_effect=slow_probe
    )
    results: list[str] = []
    threads = [
        threading.Thread(target=lambda: results.append(resolve_model()))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    try:
        if not second_waiting.wait(timeout=2):
            raise AssertionError("second caller never reached the lock")
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=2)
            if thread.is_alive():
                raise AssertionError("resolve thread still alive")

    assert results == ["M4", "M4"]
    probe.assert_called_once()


def test_cold_cache_probes_once(mocker):
    _plant(None)
    run = mocker.patch(
        "wlanpi_core.services.system_service.run_command",
        side_effect=FileNotFoundError(2, "No such file or directory: 'wlanpi-model'"),
    )

    assert cached_model() == "Unknown"
    load_platform_cache()
    assert cached_model() == "Unknown"
    run.assert_called_once()


def test_boot_model_reraises_timeout(mocker):
    exc = _timeout()
    _plant(None)
    _probe_returns(mocker, exc)

    with pytest.raises(subprocess.TimeoutExpired) as caught:
        boot_model()

    assert caught.value is exc
    assert cached_model() == "Unknown"


@pytest.mark.parametrize("raw", ["", "Go", "Unknown platform"])
def test_boot_model_returns_raw_probe(raw: str):
    _plant(raw)

    assert boot_model() == raw


def test_openapi_documents_transmit_403_only_on_gated_routes():
    spec = create_app(debug=False).openapi()
    profiler = spec["paths"]["/api/v1/profiler/start"]["post"]
    service_start = spec["paths"]["/api/v1/system/service/start"]["post"]
    pair = spec["paths"]["/api/v1/bluetooth/pair"]["post"]
    reg_domain = spec["paths"]["/api/v1/system/reg-domain/set"]["post"]

    assert "403" not in profiler.get("responses", {})
    assert "transmit is disabled" not in profiler["description"]
    assert "403" not in reg_domain.get("responses", {})

    assert f"`{GO_DETAIL}`" in pair["responses"]["403"]["description"]
    assert f"`{UNKNOWN_DETAIL}`" in pair["responses"]["403"]["description"]

    assert "403" in service_start["responses"]
    start_description = service_start["responses"]["403"]["description"]
    for unit in TRANSMIT_UNITS:
        assert f"`{unit}`" in start_description
    assert "`wlanpi-profiler`" not in start_description

    assert "403" in pair["responses"]
    assert "409" in pair["responses"]
    assert "503" in pair["responses"]

    status = spec["paths"]["/api/v1/bluetooth/status"]["get"]
    stop = spec["paths"]["/api/v1/system/service/stop"]["post"]
    assert "403" not in status.get("responses", {})
    assert "403" not in stop.get("responses", {})
