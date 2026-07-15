"""Tests for P0 worker batch: system control, hotspot, Wi-Fi, blinker, Bluetooth."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import (
    bluetooth_service,
    hotspot_service,
    system_service,
    utils_service,
)


@pytest.fixture
def client():
    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(verify_auth_wrapper, None)


def test_timezone_auto(client, mocker):
    mocker.patch.object(system_service, "run_command", return_value=MagicMock(stdout="yes\n"))
    mocker.patch.object(
        system_service, "get_timezone", return_value={"timezone": "Europe/London"}
    )

    response = client.post("/api/v1/system/timezone/auto")
    assert response.status_code == 200
    body = response.json()
    assert body["ntp"] is True
    assert body["timezone"] == "Europe/London"


def test_reboot_and_shutdown(client, mocker):
    run_command = mocker.patch("wlanpi_core.services.system_service.run_command")

    reboot = client.post("/api/v1/system/reboot")
    assert reboot.status_code == 200
    assert reboot.json()["status"] == "rebooting"

    shutdown = client.post("/api/v1/system/shutdown")
    assert shutdown.status_code == 200
    assert shutdown.json()["status"] == "shutting_down"

    assert run_command.call_args_list == [
        mocker.call(
            ["/usr/bin/systemctl", "reboot", "--no-block"],
            raise_on_fail=True,
            timeout=system_service._POWER_ACTION_TIMEOUT_SEC,
        ),
        mocker.call(
            ["/usr/bin/systemctl", "poweroff", "--no-block"],
            raise_on_fail=True,
            timeout=system_service._POWER_ACTION_TIMEOUT_SEC,
        ),
    ]


def test_hotspot_clients_requires_hotspot_mode(client, mocker):
    mocker.patch("wlanpi_core.core.mode_guard.get_mode", return_value="classic")

    response = client.get("/api/v1/system/hotspot/clients")
    assert response.status_code == 409


def test_hotspot_clients_in_hotspot_mode(client, mocker):
    mocker.patch("wlanpi_core.core.mode_guard.get_mode", return_value="hotspot")
    mocker.patch.object(
        hotspot_service,
        "resolve_ap_interface",
        return_value="wlan0",
    )
    mocker.patch.object(
        hotspot_service,
        "run_command",
        return_value=MagicMock(
            stdout="Station aa:bb:cc:dd:ee:01 (on wlan0)\nStation aa:bb:cc:dd:ee:02 (on wlan0)\n"
        ),
    )

    response = client.get("/api/v1/system/hotspot/clients")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["interface"] == "wlan0"


def test_hotspot_ssid_passphrase(client, mocker, tmp_path):
    mocker.patch("wlanpi_core.core.mode_guard.get_mode", return_value="hotspot")
    conf = tmp_path / "hostapd.conf"
    conf.write_text("ssid=TestNet\nwpa_passphrase=secret123\n")
    mocker.patch.object(
        hotspot_service,
        "_resolve_hostapd_conf",
        return_value=conf,
    )

    response = client.get("/api/v1/system/hotspot/ssid-passphrase")
    assert response.status_code == 200
    body = response.json()
    assert body["ssid"] == "TestNet"
    assert body["passphrase"] == "secret123"


def test_wifi_capabilities(client, mocker):
    mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.wifi_api.get_wifi_capabilities",
        return_value={"adapters": [{"phy": "phy0", "info": "Wiphy phy0"}]},
    )
    response = client.get("/api/v1/wifi/capabilities")
    assert response.status_code == 200
    assert response.json()["adapters"][0]["phy"] == "phy0"


def test_wifi_regulatory(client, mocker):
    mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.wifi_api.get_wifi_regulatory",
        return_value={"country": "GB", "source": "iw", "raw": "country GB"},
    )
    response = client.get("/api/v1/wifi/regulatory")
    assert response.status_code == 200
    assert response.json()["country"] == "GB"


def test_wifi_hotspot_stations_wrong_mode(client, mocker):
    mocker.patch("wlanpi_core.core.mode_guard.get_mode", return_value="classic")
    response = client.get("/api/v1/wifi/hotspot/stations")
    assert response.status_code == 409


def test_blinker_lifecycle(client, mocker):
    mocker.patch.object(
        utils_service,
        "start_port_blinker",
        return_value={"active": True, "status": "started", "interface": "eth0"},
    )
    mocker.patch.object(utils_service, "port_blinker_status", return_value={"active": True})
    mocker.patch.object(
        utils_service, "stop_port_blinker", return_value={"active": False, "status": "stopped"}
    )

    start = client.post("/api/v1/utils/blinker/start")
    assert start.status_code == 200
    assert start.json()["status"] == "started"

    status = client.get("/api/v1/utils/blinker/status")
    assert status.status_code == 200
    assert status.json()["active"] is True

    stop = client.post("/api/v1/utils/blinker/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopped"


def test_blinker_rejects_invalid_interface(client, mocker):
    popen = mocker.patch.object(utils_service.subprocess, "Popen")

    response = client.post(
        "/api/v1/utils/blinker/start",
        params={"interface": "--help"},
    )

    assert response.status_code == 400
    popen.assert_not_called()


def test_bluetooth_pair(client, mocker):
    mocker.patch.object(
        bluetooth_service,
        "bluetooth_pair",
        new=AsyncMock(
            return_value={
                "status": "discoverable",
                "alias": "wlanpi-test",
                "message": 'Bluetooth is on. Discoverable as "wlanpi-test"',
            }
        ),
    )
    response = client.post("/api/v1/bluetooth/pair")
    assert response.status_code == 200
    assert response.json()["status"] == "discoverable"


def test_bluetooth_pair_conflict(client, mocker):
    mocker.patch.object(
        bluetooth_service,
        "bluetooth_pair",
        new=AsyncMock(
            side_effect=bluetooth_service.BluetoothPairingInProgressError(
                "Bluetooth pairing is already in progress"
            )
        ),
    )
    response = client.post("/api/v1/bluetooth/pair")
    assert response.status_code == 409
    assert response.json() == {
        "error": "PAIRING_IN_PROGRESS",
        "message": "Bluetooth pairing is already in progress",
    }


def test_bluetooth_pair_failure(client, mocker):
    mocker.patch.object(
        bluetooth_service,
        "bluetooth_pair",
        new=AsyncMock(
            side_effect=bluetooth_service.BluetoothUnpairError(
                "Unable to remove the existing Bluetooth pairing before the deadline"
            )
        ),
    )
    response = client.post("/api/v1/bluetooth/pair")
    assert response.status_code == 503
    assert response.json() == {
        "error": "BLUETOOTH_PAIRING_FAILED",
        "message": "Unable to remove the existing Bluetooth pairing before the deadline",
    }


def test_legacy_wlan_set_returns_410(client):
    response = client.post(
        "/api/v1/network/wlan/set",
        json={
            "interface": "wlan0",
            "netConfig": {"id": "x", "namespaces": [], "roots": []},
            "removeAllFirst": False,
        },
    )
    assert response.status_code == 410
    assert response.json()["error"] == "ENDPOINT_DEPRECATED"


def test_legacy_wlan_scan_delegates(client, mocker):
    payload = {
        "selectedAdapter": {"iface": "wlan0", "namespace": "root", "label": "wlan0"},
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
        "scannedAt": "2026-06-06T12:00:00Z",
        "needsSelection": False,
        "candidates": [],
    }
    mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.network_api.wlan_scan",
        return_value=payload,
    )
    response = client.get(
        "/api/v1/network/wlan/scan",
        params={"type": "active", "interface": "wlan0"},
    )
    assert response.status_code == 200
    assert response.json()["nets"][0]["ssid"] == "Test"


def test_legacy_wlan_scan_reports_concurrent_scan(client, mocker):
    from wlanpi_core.wpa.scan import ScanInProgressError

    mocker.patch(
        "wlanpi_core.api.api_v1.endpoints.network_api.wlan_scan",
        side_effect=ScanInProgressError("wlan0"),
    )
    response = client.get(
        "/api/v1/network/wlan/scan",
        params={"type": "active", "interface": "wlan0"},
    )

    assert response.status_code == 409
    assert response.json()["error"] == "SCAN_IN_PROGRESS"


def test_require_mode_raises_validation_error():
    with patch("wlanpi_core.core.mode_guard.get_mode", return_value="classic"):
        with pytest.raises(ValidationError) as exc:
            hotspot_service.get_hotspot_clients()
        assert exc.value.status_code == 409
