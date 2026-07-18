"""API-level tests for utils reachability and speedtest endpoints."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper


@pytest.fixture
def client():
    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(verify_auth_wrapper, None)


def test_api_reachability_default(client):
    payload = {
        "results": {
            "Ping Google": "5ms",
            "Browse Google": "OK",
            "Ping Gateway": "1ms",
            "Arping Gateway": "1ms",
            "custom": [],
        }
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_reachability",
        new=AsyncMock(return_value=payload),
    ) as reach:
        response = client.get("/api/v1/utils/reachability")
    assert response.status_code == 200
    reach.assert_awaited_once_with(targets=None)
    assert response.json()["Ping Google"] == "5ms"
    assert response.json()["custom"] == []


def test_api_reachability_custom_targets(client):
    payload = {
        "results": {
            "Ping Google": "5ms",
            "Browse Google": "OK",
            "Ping Gateway": "1ms",
            "Arping Gateway": "1ms",
            "custom": [
                {
                    "target": "8.8.8.8",
                    "success": True,
                    "rttMsMin": 5.0,
                    "rttMsAvg": 5.0,
                    "rttMsMax": 5.0,
                    "packetLossPercent": 0.0,
                    "display": "5.0ms",
                }
            ],
        }
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_reachability",
        new=AsyncMock(return_value=payload),
    ) as reach:
        response = client.get(
            "/api/v1/utils/reachability",
            params=[("targets", "8.8.8.8"), ("targets", "1.1.1.1")],
        )
    assert response.status_code == 200
    reach.assert_awaited_once_with(targets=["8.8.8.8", "1.1.1.1"])
    assert response.json()["custom"][0]["target"] == "8.8.8.8"


def test_api_reachability_invalid_targets(client):
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_reachability",
        new=AsyncMock(return_value={"error": "invalid ping target: bad;host"}),
    ):
        response = client.get(
            "/api/v1/utils/reachability",
            params={"targets": "bad;host"},
        )
    assert response.status_code == 400


def test_api_speedtest(client):
    payload = {
        "results": {
            "ipAddress": "1.2.3.4",
            "downloadSpeed": "100.00 Mbps",
            "uploadSpeed": "50.00 Mbps",
            "pingMs": 5.0,
            "jitterMs": 0.0,
            "server": "Test Server",
            "testedAt": "2026-06-14T17:38:48+00:00",
        }
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_speedtest",
        new=AsyncMock(return_value=payload),
    ):
        response = client.get("/api/v1/utils/speedtest")
    assert response.status_code == 200
    body = response.json()
    assert body["ipAddress"] == "1.2.3.4"
    assert body["downloadSpeed"] == "100.00 Mbps"


def test_api_speedtest_failure(client):
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_speedtest",
        new=AsyncMock(return_value={"error": "speedtest failed"}),
    ):
        response = client.get("/api/v1/utils/speedtest")
    assert response.status_code == 503
