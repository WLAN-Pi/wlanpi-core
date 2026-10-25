from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from wlanpi_core.api.openapi_docs import (
    TRANSMIT_DISABLED_ON_GO,
    TRANSMIT_DISABLED_UNKNOWN,
)
from wlanpi_core.api.transmit_gate import (
    GATED_OPERATIONS,
    TRANSMIT_SERVICE_NAMES,
    enforce_transmit_gate,
)
from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.services import system_service

_SPEC_TRANSMIT_SERVICES = frozenset(
    {
        "hostapd",
        "wlanpi-profiler",
        "wpa_supplicant",
        "wpa_supplicant@wlan0",
        "kismet",
        "wlanpi-grafana-scanner-wlan0",
        "wlanpi-grafana-scanner-wlan1",
        "wlanpi-grafana-scanner-wlan2",
        "bt-agent",
        "bt-network",
    }
)

_PROFILER_START = "wlanpi_core.api.api_v1.endpoints.profiler_api.cli.start_profiler"
_SERVICE_START = (
    "wlanpi_core.api.api_v1.endpoints.system_api.system_service.start_systemd_service"
)
_SERVICE_STOP = (
    "wlanpi_core.api.api_v1.endpoints.system_api.system_service.stop_systemd_service"
)
_SERVICE_RESTART = (
    "wlanpi_core.api.api_v1.endpoints.system_api.system_service.restart_systemd_service"
)


@pytest.fixture
def client():
    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(verify_auth_wrapper, None)


def _assert_refused(response, detail: str) -> None:
    assert response.status_code == 403
    assert response.json() == {"detail": detail}


def _patch_profiler(mocker):
    return mocker.patch(
        _PROFILER_START,
        new_callable=AsyncMock,
        return_value={"success": True},
    )


def _patch_power(mocker):
    mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.bluetooth_api.bluetooth_service.bluetooth_adapter",
        return_value="hci0",
    )
    mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.bluetooth_api.bluetooth_service.bluetooth_present",
        return_value=True,
    )
    return mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.bluetooth_api.bluetooth_service.bluetooth_set_power",
        return_value=True,
    )


@pytest.mark.parametrize(
    ("model", "detail"),
    [
        ("Go", TRANSMIT_DISABLED_ON_GO),
        ("Unknown", TRANSMIT_DISABLED_UNKNOWN),
        ("Unknown platform", TRANSMIT_DISABLED_UNKNOWN),
        ("", TRANSMIT_DISABLED_UNKNOWN),
        (None, TRANSMIT_DISABLED_UNKNOWN),
    ],
)
def test_profiler_start_refuses_unusable_models(client, mocker, model, detail):
    system_service.set_cached_platform(model)
    starter = _patch_profiler(mocker)

    response = client.post("/api/v1/profiler/start", json={})

    _assert_refused(response, detail)
    starter.assert_not_called()


def test_profiler_start_refuses_go_when_no_ap_is_set(client, mocker):
    system_service.set_cached_platform("Go")
    starter = _patch_profiler(mocker)

    response = client.post("/api/v1/profiler/start", json={"noAP": True})

    _assert_refused(response, TRANSMIT_DISABLED_ON_GO)
    starter.assert_not_called()


@pytest.mark.parametrize("model", ["M4", "M4+", "R4", "R5", "Pro"])
def test_profiler_start_allows_other_models(client, mocker, model):
    system_service.set_cached_platform(model)
    starter = _patch_profiler(mocker)

    response = client.post("/api/v1/profiler/start", json={})

    assert response.status_code == 200
    starter.assert_called_once()


def test_go_allows_profiler_and_bluetooth_status(client, mocker):
    system_service.set_cached_platform("Go")
    profiler = mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.profiler_api.service.get_status",
        return_value={"running": False},
    )
    bluetooth = mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.bluetooth_api.bluetooth_service.bluetooth_status",
        return_value={
            "name": "wlanpi",
            "alias": "wlanpi",
            "addr": "00:00:00:00:00:00",
            "power": "Off",
            "blocked": False,
            "paired_devices": [],
        },
    )

    profiler_response = client.get("/api/v1/profiler/status")
    bluetooth_response = client.get("/api/v1/bluetooth/status")

    assert profiler_response.status_code == 200
    assert bluetooth_response.status_code == 200
    profiler.assert_called_once()
    bluetooth.assert_called_once()


def test_go_refuses_bluetooth_power_on_and_allows_off(client, mocker):
    system_service.set_cached_platform("Go")
    setter = _patch_power(mocker)

    refused = client.post("/api/v1/bluetooth/power/on")
    _assert_refused(refused, TRANSMIT_DISABLED_ON_GO)
    setter.assert_not_called()

    allowed = client.post("/api/v1/bluetooth/power/off")
    assert allowed.status_code == 200
    setter.assert_called_once()


@pytest.mark.parametrize("name", ["hostapd", "Hostapd", "hostapd.service"])
def test_go_refuses_transmit_service_start(client, mocker, name):
    system_service.set_cached_platform("Go")
    starter = mocker.patch(
        _SERVICE_START,
        new_callable=AsyncMock,
        return_value={"name": "hostapd", "active": True},
    )

    response = client.post("/api/v1/system/service/start", params={"name": name})

    _assert_refused(response, TRANSMIT_DISABLED_ON_GO)
    starter.assert_not_called()


@pytest.mark.parametrize("name", ["iperf3", "wpa_supplicant@wlan1"])
def test_go_allows_non_transmit_service_start(client, mocker, name):
    system_service.set_cached_platform("Go")
    starter = mocker.patch(
        _SERVICE_START,
        new_callable=AsyncMock,
        return_value={"name": name, "active": True},
    )

    response = client.post("/api/v1/system/service/start", params={"name": name})

    assert response.status_code == 200
    starter.assert_called_once()


def test_missing_service_name_is_not_refused(client, mocker):
    system_service.set_cached_platform("Go")
    starter = mocker.patch(
        _SERVICE_START,
        new_callable=AsyncMock,
        return_value={"name": "hostapd", "active": True},
    )

    response = client.post("/api/v1/system/service/start")

    assert response.status_code == 422
    starter.assert_not_called()


def test_go_allows_service_stop(client, mocker):
    system_service.set_cached_platform("Go")
    stopper = mocker.patch(
        _SERVICE_STOP,
        new_callable=AsyncMock,
        return_value={"name": "hostapd", "active": False},
    )

    response = client.post("/api/v1/system/service/stop", params={"name": "hostapd"})

    assert response.status_code == 200
    stopper.assert_called_once()


def test_go_refuses_restart_for_every_transmit_service(client, mocker):
    system_service.set_cached_platform("Go")
    restarter = mocker.patch(
        _SERVICE_RESTART,
        new_callable=AsyncMock,
        return_value={"name": "hostapd", "active": True},
    )

    for name in sorted(TRANSMIT_SERVICE_NAMES):
        response = client.post("/api/v1/system/service/restart", params={"name": name})
        _assert_refused(response, TRANSMIT_DISABLED_ON_GO)
    restarter.assert_not_called()


def test_transmit_service_names_match_the_spec_roster():
    assert TRANSMIT_SERVICE_NAMES == _SPEC_TRANSMIT_SERVICES


def test_go_refuses_activate_reg_domain_pair_and_scans(client, mocker):
    system_service.set_cached_platform("Go")
    activate = mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.network_config_api.network_config.activate_config_report",
        return_value=(True, []),
    )
    reg_domain = mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.system_api.system_service.set_reg_domain",
        return_value={"country": "US", "raw": "US", "source": "iw"},
    )
    pair = mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.bluetooth_api.bluetooth_service.bluetooth_pair",
        new_callable=AsyncMock,
        return_value={
            "status": "discoverable",
            "alias": "wlanpi",
            "message": "pairing",
        },
    )
    utils_scan = mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.wlan_scan",
        return_value={"networks": []},
    )
    legacy_scan = mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.network_api.wlan_scan",
        return_value={"networks": []},
    )

    activate_response = client.post("/api/v1/network/config/activate/monitor")
    reg_response = client.post("/api/v1/system/reg-domain/set", json={"country": "US"})
    pair_response = client.post("/api/v1/bluetooth/pair")
    utils_response = client.get("/api/v1/utils/wlan/scan")
    legacy_response = client.get(
        "/api/v1/network/wlan/scan",
        params={"type": "full", "interface": "wlan0"},
    )

    _assert_refused(activate_response, TRANSMIT_DISABLED_ON_GO)
    _assert_refused(reg_response, TRANSMIT_DISABLED_ON_GO)
    _assert_refused(pair_response, TRANSMIT_DISABLED_ON_GO)
    _assert_refused(utils_response, TRANSMIT_DISABLED_ON_GO)
    _assert_refused(legacy_response, TRANSMIT_DISABLED_ON_GO)
    activate.assert_not_called()
    reg_domain.assert_not_called()
    pair.assert_not_called()
    utils_scan.assert_not_called()
    legacy_scan.assert_not_called()


def test_go_refuses_profiler_start_before_auth(client, mocker):
    app.dependency_overrides.pop(verify_auth_wrapper, None)
    system_service.set_cached_platform("Go")
    starter = _patch_profiler(mocker)

    response = client.post("/api/v1/profiler/start", json={})

    _assert_refused(response, TRANSMIT_DISABLED_ON_GO)
    starter.assert_not_called()


def test_allowed_model_without_credentials_is_unauthorized(client, mocker):
    app.dependency_overrides.pop(verify_auth_wrapper, None)
    system_service.set_cached_platform("M4")
    starter = _patch_profiler(mocker)

    response = client.post("/api/v1/profiler/start", json={})

    assert response.status_code == 401
    starter.assert_not_called()


def test_openapi_documents_403_only_on_gated_operations():
    schema = app.openapi()
    for method, path in GATED_OPERATIONS:
        operation = schema["paths"][path][method.lower()]
        forbidden = operation["responses"]["403"]
        assert TRANSMIT_DISABLED_ON_GO in forbidden["description"]
        assert TRANSMIT_DISABLED_UNKNOWN in forbidden["description"]
        assert "startup cache that was never filled" in forbidden["description"]
        ref = forbidden["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/MessageResponse")

    assert "403" not in schema["paths"]["/api/v1/profiler/status"]["get"]["responses"]
    assert (
        "403" not in schema["paths"]["/api/v1/system/service/stop"]["post"]["responses"]
    )
    pair = schema["paths"]["/api/v1/bluetooth/pair"]["post"]["responses"]
    assert "409" in pair
    assert "503" in pair
    assert "409" in schema["paths"]["/api/v1/utils/wlan/scan"]["get"]["responses"]
    assert "409" in schema["paths"]["/api/v1/network/wlan/scan"]["get"]["responses"]


def test_transmit_phrase_is_only_on_gated_operations():
    gated_endpoints: set[object] = set()
    covered: set[tuple[str, str]] = set()
    seen: list[tuple[object, str]] = []
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute) or context.path is None:
            continue
        doc = route.endpoint.__doc__ or ""
        seen.append((route.endpoint, doc))
        for method in route.methods or set():
            lookup = "GET" if method == "HEAD" else method
            key = (lookup, context.path)
            if key in GATED_OPERATIONS:
                gated_endpoints.add(route.endpoint)
                covered.add(key)

    assert covered == set(GATED_OPERATIONS)
    for endpoint, doc in seen:
        if endpoint in gated_endpoints:
            assert "Transmit is disabled" in doc
        else:
            assert "Transmit is disabled" not in doc, endpoint


def test_original_route_dependant_does_not_require_transmit_gate():
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute):
            continue
        calls = [dependency.call for dependency in route.dependant.dependencies]
        assert enforce_transmit_gate not in calls


def test_device_reads_follow_cached_platform_without_exec(client, mocker):
    from wlanpi_core.api.api_v1.endpoints import system_api

    mocker.patch.object(
        system_service,
        "_read_wlanpi_model",
        side_effect=AssertionError("wlanpi-model executed"),
    )
    mocker.patch.object(
        system_api.system_service,
        "get_hostname",
        return_value="wlanpi.local",
    )
    mocker.patch.object(
        system_api.system_service,
        "get_image_ver",
        return_value="3.0.0",
    )
    system_api._read_static_device_info.cache_clear()
    try:
        system_service.set_cached_platform("R5")
        model = client.get("/api/v1/system/device/model")
        info = client.get("/api/v1/system/device/info")
        assert model.status_code == 200
        assert model.json() == {"model": "R5"}
        assert info.status_code == 200
        assert info.json()["model"] == "R5"

        system_service.set_cached_platform("Pro")
        model = client.get("/api/v1/system/device/model")
        info = client.get("/api/v1/system/device/info")
        assert model.json() == {"model": "Pro"}
        assert info.json()["model"] == "Pro"
    finally:
        system_api._read_static_device_info.cache_clear()


def test_load_platform_stores_unknown_and_does_not_exec_again(mocker):
    system_service.set_cached_platform(None)
    run = mocker.patch.object(
        system_service,
        "run_command",
        side_effect=FileNotFoundError(2, "wlanpi-model"),
    )

    assert system_service.load_platform() == "Unknown"
    assert system_service.get_platform() == "Unknown"
    assert system_service.get_model() == "Unknown"
    assert system_service.load_platform() == "Unknown"
    assert run.call_count == 1
