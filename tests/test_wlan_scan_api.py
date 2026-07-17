"""API-level tests for GET /api/v1/utils/wlan/scan."""
from unittest.mock import patch

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


def test_api_wlan_scan_auto_single_monitor(client):
    payload = {
        "selectedAdapter": {
            "iface": "wlanpi0",
            "namespace": "root",
            "label": "wlanpi0 (monitor, root)",
            "mode": "monitor",
        },
        "networks": [
            {
                "ssid": "Test",
                "bssid": "aa:bb:cc:dd:ee:01",
                "signal": -50,
                "freq": 2412,
                "key_mgmt": "wpa-psk",
                "minrate": 1_000_000,
            }
        ],
        "scannedAt": "2026-06-06T12:00:00+00:00",
        "needsSelection": False,
        "candidates": [],
    }
    with patch("wlanpi_core.api.api_v1.endpoints.utils_api.wlan_scan", return_value=payload):
        response = client.get("/api/v1/utils/wlan/scan")
    assert response.status_code == 200
    body = response.json()
    assert body["selectedAdapter"]["iface"] == "wlanpi0"
    assert body["networks"][0]["ssid"] == "Test"


def test_api_wlan_scan_needs_selection(client):
    payload = {
        "needsSelection": True,
        "candidates": [
            {"iface": "wlanpi0", "namespace": "root", "label": "wlanpi0"},
            {"iface": "wlanpi1", "namespace": "root", "label": "wlanpi1"},
        ],
        "selectedAdapter": None,
        "networks": [],
        "scannedAt": None,
    }
    with patch("wlanpi_core.api.api_v1.endpoints.utils_api.wlan_scan", return_value=payload):
        response = client.get("/api/v1/utils/wlan/scan")
    assert response.status_code == 200
    body = response.json()
    assert body["needsSelection"] is True
    assert len(body["candidates"]) == 2
    assert body["networks"] == []


def test_api_wlan_scan_no_adapter(client):
    from wlanpi_core.wlan.scan import NoScanAdapterError

    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.wlan_scan",
        side_effect=NoScanAdapterError(),
    ):
        response = client.get("/api/v1/utils/wlan/scan")
    assert response.status_code == 422
    assert response.json()["error"] == "NO_SCAN_ADAPTER"


def test_api_wlan_scan_reports_concurrent_scan(client):
    from wlanpi_core.wpa.scan import ScanInProgressError

    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.wlan_scan",
        side_effect=ScanInProgressError("wlan0"),
    ):
        response = client.get("/api/v1/utils/wlan/scan")

    assert response.status_code == 409
    assert response.json() == {
        "error": "SCAN_IN_PROGRESS",
        "message": "A scan is already in progress on wlan0 in root",
    }


def test_api_wlan_scan_explicit_iface_namespace(client):
    payload = {
        "selectedAdapter": {
            "iface": "wlanpi1",
            "namespace": "scan_ns",
            "label": "wlanpi1 (monitor, scan_ns)",
            "mode": "monitor",
        },
        "networks": [],
        "scannedAt": "2026-06-06T12:00:00+00:00",
        "needsSelection": False,
        "candidates": [],
    }
    with patch("wlanpi_core.api.api_v1.endpoints.utils_api.wlan_scan", return_value=payload) as scan:
        response = client.get(
            "/api/v1/utils/wlan/scan",
            params={"iface": "wlanpi1", "namespace": "scan_ns"},
        )
    assert response.status_code == 200
    scan.assert_called_once()
    assert scan.call_args.kwargs["iface"] == "wlanpi1"
    assert scan.call_args.kwargs["namespace"] == "scan_ns"


def test_api_wlan_scan_detail_full_passthrough(client):
    payload = {
        "detail": "full",
        "selectedAdapter": {
            "iface": "wlan0",
            "namespace": "root",
            "label": "wlan0 (managed, root)",
            "mode": "managed",
        },
        "networks": [
            {
                "ssid": "Test",
                "bssid": "aa:bb:cc:dd:ee:01",
                "signal": -50,
                "freq": 2412,
                "key_mgmt": "wpa-psk",
                "minrate": 1_000_000,
                "raw": "BSS aa:bb:cc:dd:ee:01(on wlan0)\n\tSSID: Test",
            }
        ],
        "scannedAt": "2026-06-06T12:00:00+00:00",
        "needsSelection": False,
        "candidates": [],
    }
    with patch("wlanpi_core.api.api_v1.endpoints.utils_api.wlan_scan", return_value=payload) as scan:
        response = client.get("/api/v1/utils/wlan/scan", params={"detail": "full"})
    assert response.status_code == 200
    assert response.json()["networks"][0]["raw"].startswith("BSS ")
    scan.assert_called_once_with(
        iface=None,
        namespace=None,
        hidden=True,
        detail="full",
    )


def test_api_wlan_scan_invalid_detail(client):
    with patch("wlanpi_core.api.api_v1.endpoints.utils_api.wlan_scan") as scan:
        scan.side_effect = ValueError("detail must be one of: full, short")
        response = client.get("/api/v1/utils/wlan/scan", params={"detail": "verbose"})
    assert response.status_code == 400
    assert "detail must be one of" in response.text


def test_api_wlan_scan_error_never_returned_as_200(client):
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.wlan_scan",
        return_value={"error": "scan failed", "networks": []},
    ):
        response = client.get("/api/v1/utils/wlan/scan")
    assert response.status_code == 503
    assert response.json()["error"] == "scan failed"
