from __future__ import annotations

import subprocess
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
    GO_DETAIL,
    TRANSMIT_UNITS,
    UNKNOWN_DETAIL,
    refusal_detail,
    require_transmit,
    require_transmit_for_activate,
    require_transmit_for_power,
    require_transmit_for_unit,
)
from wlanpi_core.services import bluetooth_service, system_service
from wlanpi_core.services.platform_cache import (
    ModelToken,
    PlatformSnapshot,
    boot_model,
    cached_model,
    clear_platform_cache,
    load_platform_cache,
    store_platform_snapshot,
    token_from_snapshot,
)

_TRANSMIT_DEPENDENCIES = {
    require_transmit,
    require_transmit_for_unit,
    require_transmit_for_power,
    require_transmit_for_activate,
}

_GATED_ROUTES = {
    ("POST", "/api/v1/network/config/activate/{id}"): require_transmit_for_activate,
    ("POST", "/api/v1/system/reg-domain/set"): require_transmit,
    ("POST", "/api/v1/bluetooth/pair"): require_transmit,
    ("POST", "/api/v1/system/service/start"): require_transmit_for_unit,
    ("POST", "/api/v1/system/service/restart"): require_transmit_for_unit,
    ("POST", "/api/v1/bluetooth/power/{action}"): require_transmit_for_power,
}

_UNGATED_ROUTES = (
    ("POST", "/api/v1/profiler/start"),
    ("POST", "/api/v1/profiler/stop"),
    ("POST", "/api/v1/profiler/purge"),
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


@pytest.fixture
def client():
    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(verify_auth_wrapper, None)


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (PlatformSnapshot(model="M4", error=_timeout()), "Unknown"),
        (PlatformSnapshot(model="", error=None), "Unknown"),
        (PlatformSnapshot(model="M4?", error=None), "Unknown"),
        (PlatformSnapshot(model="Unknown", error=None), "Unknown"),
        (PlatformSnapshot(model="Go", error=None), "Go"),
        (PlatformSnapshot(model="go", error=None), "go"),
        (PlatformSnapshot(model="Go2", error=None), "Go2"),
        (PlatformSnapshot(model="Pro", error=None), "Pro"),
        (PlatformSnapshot(model="M4+", error=None), "M4+"),
    ],
)
def test_token_from_snapshot(snapshot: PlatformSnapshot, expected: str):
    assert token_from_snapshot(snapshot).value == expected


@pytest.mark.parametrize("value", ["", "Go?"])
def test_model_token_rejects_blank_and_question_suffix(value: str):
    with pytest.raises(ValueError):
        ModelToken(value)


@pytest.mark.parametrize(
    ("value", "detail"),
    [
        ("Go", GO_DETAIL),
        ("Unknown", UNKNOWN_DETAIL),
        ("M4", None),
        ("M4+", None),
        ("R4", None),
        ("Pro", None),
        ("go", None),
        ("Go2", None),
    ],
)
def test_refusal_detail(value: str, detail: str | None):
    assert refusal_detail(ModelToken(value)) == detail


def test_cached_model_cold_is_unknown_and_does_not_probe(mocker):
    run = mocker.patch(
        "wlanpi_core.services.system_service.run_command",
        side_effect=AssertionError("probed"),
    )
    clear_platform_cache()

    assert cached_model().value == "Unknown"
    run.assert_not_called()


def test_load_platform_cache_file_not_found_is_idempotent(mocker):
    run = mocker.patch(
        "wlanpi_core.services.system_service.run_command",
        side_effect=FileNotFoundError(2, "No such file or directory: 'wlanpi-model'"),
    )
    clear_platform_cache()

    first = load_platform_cache()

    assert first.model == "Unknown"
    assert first.error is None
    assert cached_model().value == "Unknown"
    assert run.call_count == 1

    second = load_platform_cache()

    assert second == first
    assert run.call_count == 1


def test_load_platform_cache_stores_timeout(mocker):
    exc = _timeout()
    mocker.patch(
        "wlanpi_core.services.system_service.get_platform",
        side_effect=exc,
    )
    clear_platform_cache()

    snapshot = load_platform_cache()

    assert snapshot.model == ""
    assert snapshot.error is exc
    assert cached_model().value == "Unknown"


def test_boot_model_reraises_timeout():
    exc = _timeout()
    store_platform_snapshot(PlatformSnapshot(model="", error=exc))

    with pytest.raises(subprocess.TimeoutExpired) as caught:
        boot_model()

    assert caught.value is exc


def test_boot_model_returns_empty_string():
    store_platform_snapshot(PlatformSnapshot(model="", error=None))

    assert boot_model() == ""


def test_boot_model_returns_go():
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))

    assert boot_model() == "Go"


def test_boot_model_cold_raises():
    clear_platform_cache()

    with pytest.raises(RuntimeError, match="platform model was not loaded at startup"):
        boot_model()


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


@pytest.mark.parametrize(
    "snapshot",
    [
        PlatformSnapshot(model="Go", error=None),
        PlatformSnapshot(model="Unknown", error=None),
        PlatformSnapshot(model="", error=None),
        PlatformSnapshot(model="M4", error=_timeout()),
    ],
)
def test_profiler_start_reaches_downstream_including_no_ap(client, mocker, snapshot):
    store_platform_snapshot(snapshot)
    start = mocker.patch.object(
        profiler_api.cli,
        "start_profiler",
        new=AsyncMock(return_value={"success": True}),
    )

    response = client.post("/api/v1/profiler/start", json={"noAP": True})

    assert response.status_code == 200
    start.assert_awaited()


@pytest.mark.parametrize(
    "snapshot",
    [
        PlatformSnapshot(model="Go", error=None),
        PlatformSnapshot(model="Unknown", error=None),
        PlatformSnapshot(model="", error=None),
        PlatformSnapshot(model="M4", error=_timeout()),
    ],
)
def test_reg_domain_set_refused_when_model_untrusted(client, mocker, snapshot):
    store_platform_snapshot(snapshot)
    set_domain = mocker.patch.object(system_api.system_service, "set_reg_domain")

    response = client.post(
        "/api/v1/system/reg-domain/set",
        json={"country": "US"},
    )

    detail = GO_DETAIL if snapshot.model == "Go" else UNKNOWN_DETAIL
    assert response.status_code == 403
    assert response.json() == {"detail": detail}
    set_domain.assert_not_called()


@pytest.mark.parametrize("model", ["M4", "M4+", "R4", "Pro"])
def test_profiler_start_allowed_models_reach_downstream(client, mocker, model: str):
    store_platform_snapshot(PlatformSnapshot(model=model, error=None))
    start = mocker.patch.object(
        profiler_api.cli,
        "start_profiler",
        new=AsyncMock(return_value={"success": True}),
    )

    response = client.post("/api/v1/profiler/start", json={"noAP": True})

    assert response.status_code == 200
    start.assert_awaited()


def test_profiler_start_without_auth_is_401_not_transmit_detail():
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))

    with TestClient(app) as raw_client:
        response = raw_client.post("/api/v1/profiler/start", json={"noAP": True})

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication required: Bearer token or request signature"
    }


def test_bluetooth_status_on_go_is_not_403(client, mocker):
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))
    mocker.patch.object(
        bluetooth_service,
        "bluetooth_status",
        return_value=_BLUETOOTH_STATUS,
    )

    response = client.get("/api/v1/bluetooth/status")

    assert response.status_code == 200


def test_service_start_cockpit_on_go_reaches_downstream(client, mocker):
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))
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
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))
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
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))
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
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))
    mocker.patch.object(bluetooth_service, "bluetooth_adapter", return_value="hci0")
    mocker.patch.object(bluetooth_service, "bluetooth_present", return_value=True)
    set_power = mocker.patch.object(
        bluetooth_service, "bluetooth_set_power", return_value=True
    )

    response = client.post("/api/v1/bluetooth/power/off")

    assert response.status_code == 200
    set_power.assert_called_once_with(False, "hci0")


def test_bluetooth_power_on_on_go_is_403(client, mocker):
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))
    set_power = mocker.patch.object(
        bluetooth_service, "bluetooth_set_power", return_value=True
    )

    response = client.post("/api/v1/bluetooth/power/on")

    assert response.status_code == 403
    assert response.json() == {"detail": GO_DETAIL}
    set_power.assert_not_called()


def test_bluetooth_power_banana_on_go_is_plain_text_400(client, mocker):
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))
    set_power = mocker.patch.object(
        bluetooth_service, "bluetooth_set_power", return_value=True
    )

    response = client.post("/api/v1/bluetooth/power/banana")

    assert response.status_code == 400
    assert response.text == "Invalid action. Use 'on' or 'off'."
    set_power.assert_not_called()


def test_activate_manual_on_m4_is_409(client, mocker, monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "manual")
    store_platform_snapshot(PlatformSnapshot(model="M4", error=None))
    activate = mocker.patch.object(
        network_config_api.network_config, "activate_config_report"
    )

    response = client.post("/api/v1/network/config/activate/lab_cfg")

    assert response.status_code == 409
    assert "WLAN_MANAGEMENT=manual" in response.json()["detail"]
    activate.assert_not_called()


def test_activate_go_manual_is_409_before_transmit_refusal(client, mocker, monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "manual")
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))
    activate = mocker.patch.object(
        network_config_api.network_config, "activate_config_report"
    )

    response = client.post("/api/v1/network/config/activate/lab_cfg")

    assert response.status_code == 409
    assert "WLAN_MANAGEMENT=manual" in response.json()["detail"]
    activate.assert_not_called()


def test_activate_go_auto_is_transmit_403(client, mocker, monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "auto")
    store_platform_snapshot(PlatformSnapshot(model="Go", error=None))
    activate = mocker.patch.object(
        network_config_api.network_config, "activate_config_report"
    )

    response = client.post("/api/v1/network/config/activate/lab_cfg")

    assert response.status_code == 403
    assert response.json() == {"detail": GO_DETAIL}
    activate.assert_not_called()


def test_openapi_documents_transmit_403_only_on_gated_routes():
    spec = create_app(debug=False).openapi()
    profiler = spec["paths"]["/api/v1/profiler/start"]["post"]
    service_start = spec["paths"]["/api/v1/system/service/start"]["post"]
    pair = spec["paths"]["/api/v1/bluetooth/pair"]["post"]
    reg_domain = spec["paths"]["/api/v1/system/reg-domain/set"]["post"]

    assert "403" not in profiler.get("responses", {})
    assert "transmit is disabled" not in profiler["description"]

    assert "403" in reg_domain["responses"]
    assert f"`{GO_DETAIL}`" in reg_domain["responses"]["403"]["description"]
    assert f"`{UNKNOWN_DETAIL}`" in reg_domain["responses"]["403"]["description"]

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
