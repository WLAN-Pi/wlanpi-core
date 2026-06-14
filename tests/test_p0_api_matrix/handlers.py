"""Scenario handlers for p0_api_test_matrix.csv rows.

Mocking policy: stub adapter enumeration only for hardware layout rows;
stub run_command for CLI wrappers; keep FastAPI routing and auth real.
"""
from __future__ import annotations

from typing import Callable
from unittest.mock import patch

from tests.scenarios.p0_loader import ApiScenario

# scenario name → handler(client, auth_headers, scenario)
HANDLERS: dict[str, Callable] = {}


def _expect_status(response, expected: str) -> None:
    if " or " in expected:
        codes = {int(code.strip()) for code in expected.split(" or ")}
        assert response.status_code in codes
    elif "/" in expected:
        assert response.status_code in {int(code) for code in expected.split("/")}
    else:
        assert response.status_code == int(expected)


def handle_service_restart_orb(client, auth_headers, scenario):
    with patch("wlanpi_core.services.system_service.restart_service", return_value=True):
        with patch("wlanpi_core.services.system_service.is_allowed_service", return_value=True):
            response = client.post("/api/v1/system/service/restart?name=orb")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["name"] == "orb"
    assert body["active"] is True


def handle_service_restart_not_allowed(client, auth_headers, scenario):
    response = client.post("/api/v1/system/service/restart?name=evil")
    _expect_status(response, scenario.expected_http)


def handle_publicip6(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.services.network_info_service.run_command",
        return_value=type("R", (), {"stdout": "2001:db8::1\n"})(),
    ):
        response = client.get("/api/v1/network/info/publicip6")
    _expect_status(response, scenario.expected_http)
    assert "info" in response.json()


def handle_timezone_get_set(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.services.system_service.run_command",
        return_value=type("R", (), {"stdout": "Europe/London\n"})(),
    ):
        with patch("wlanpi_core.services.system_service.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            get_resp = client.get("/api/v1/system/timezone")
            assert get_resp.status_code == 200
            with patch(
                "wlanpi_core.services.system_service.set_timezone",
                return_value={"timezone": "Europe/London"},
            ):
                set_resp = client.post(
                    "/api/v1/system/timezone/set",
                    json={"timezone": "Europe/London"},
                )
    assert set_resp.status_code == 200
    assert set_resp.json()["timezone"] == "Europe/London"


def handle_system_device_info_any_mode(client, auth_headers, scenario):
    response = client.get("/api/v1/system/device/info")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert "mode" in body
    assert "hostname" in body


def handle_utils_reachability_live(client, auth_headers, scenario):
    from unittest.mock import AsyncMock

    reachability_results = {
        "Ping Google": "1ms",
        "Browse Google": "OK",
        "Ping Gateway": "1ms",
        "Arping Gateway": "1ms",
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_reachability",
        new=AsyncMock(return_value={"results": reachability_results}),
    ):
        response = client.get("/api/v1/utils/reachability")
    _expect_status(response, scenario.expected_http)


def handle_reg_domain_list(client, auth_headers, scenario):
    response = client.get("/api/v1/system/reg-domain/list")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert len(body["countries"]) == 9
    assert body["countries"][0]["code"]
    assert body["countries"][0]["name"]


def handle_routing_table(client, auth_headers, scenario):
    sample = [{"dst": "default", "gateway": "10.10.0.254", "dev": "eth0"}]
    with patch(
        "wlanpi_core.network.routing.ns_exec",
        return_value=type("R", (), {"stdout": __import__("json").dumps(sample)})(),
    ):
        response = client.get("/api/v1/network/routing")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert "routes" in body
    assert len(body["routes"]) >= 1


HANDLERS.update(
    {
        "service_restart_orb": handle_service_restart_orb,
        "service_restart_not_allowed": handle_service_restart_not_allowed,
        "publicip6": handle_publicip6,
        "timezone_get_set": handle_timezone_get_set,
        "system_device_info_any_mode": handle_system_device_info_any_mode,
        "utils_reachability_live": handle_utils_reachability_live,
        "reg_domain_list": handle_reg_domain_list,
        "routing_table": handle_routing_table,
    }
)


def run_api_scenario(scenario: ApiScenario, client, auth_headers) -> None:
    handler = HANDLERS.get(scenario.name)
    if handler is None:
        raise KeyError(f"No handler for {scenario.name}")
    handler(client, auth_headers, scenario)
