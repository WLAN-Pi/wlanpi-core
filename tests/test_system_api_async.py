"""Concurrency checks for system API handlers."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from wlanpi_core.api.api_v1.endpoints import system_api
from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper


def test_device_info_caches_static_fields_but_not_mode(mocker):
    get_platform = mocker.patch.object(
        system_api.system_service,
        "get_platform",
        return_value="WLAN Pi Pro",
    )
    get_hostname = mocker.patch.object(
        system_api.system_service,
        "get_hostname",
        return_value="wlanpi.local",
    )
    get_image_ver = mocker.patch.object(
        system_api.system_service,
        "get_image_ver",
        return_value="3.0.0",
    )
    get_mode = mocker.patch.object(
        system_api.system_service,
        "get_mode",
        side_effect=["classic", "hotspot"],
    )
    system_api._read_static_device_info.cache_clear()

    try:
        first = system_api._read_device_info()
        second = system_api._read_device_info()
    finally:
        system_api._read_static_device_info.cache_clear()

    assert first["mode"] == "classic"
    assert second["mode"] == "hotspot"
    get_platform.assert_called_once_with()
    get_hostname.assert_called_once_with()
    get_image_ver.assert_called_once_with()
    assert get_mode.call_count == 2


@pytest.mark.asyncio
async def test_device_stats_does_not_block_event_loop(mocker):
    started = threading.Event()
    release = threading.Event()
    expected = {
        "ip": "127.0.0.1",
        "cpu": "0%",
        "ram": "0/0MB 0%",
        "disk": "0/0GB 0%",
        "cpu_temp": "0C",
        "uptime": "0m",
    }

    def blocking_stats():
        started.set()
        release.wait(timeout=1)
        return expected

    mocker.patch.object(system_api.system_service, "get_stats", blocking_stats)
    task = asyncio.create_task(system_api.device_stats())

    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0)

        assert started.is_set()
        assert not task.done()
    finally:
        release.set()

    assert await task == expected


def test_api_health_serializes():
    async def _allow():
        return True

    payload = {
        "throttled": {
            "raw": "throttled=0x0",
            "undervoltage": False,
            "frequency_capped": False,
            "throttled": False,
            "soft_temperature_limit": False,
            "undervoltage_occurred": False,
            "frequency_capped_occurred": False,
            "throttled_occurred": False,
            "soft_temperature_limit_occurred": False,
        },
        "temperatures": [{"name": "cpu_thermal", "label": None, "celsius": 60.0}],
        "ntp": {"enabled": True, "synchronized": False},
        "load": {"one": 0.1, "five": 0.2, "fifteen": 0.3},
        "swap": {"used_mb": 1, "total_mb": 2},
        "rfkill": [],
    }

    app.dependency_overrides[verify_auth_wrapper] = _allow
    try:
        with TestClient(app) as client:
            with patch.object(
                system_api.system_service, "get_health", return_value=payload
            ):
                response = client.get("/api/v1/system/health")
    finally:
        app.dependency_overrides.pop(verify_auth_wrapper, None)

    assert response.status_code == 200
    assert response.json()["ntp"] == {"enabled": True, "synchronized": False}
    assert response.json()["temperatures"][0]["celsius"] == 60.0


def test_api_failed_services_serializes():
    async def _allow():
        return True

    payload = {
        "units": [
            {
                "unit": "bt-agent.service",
                "load": "loaded",
                "active": "failed",
                "sub": "failed",
                "description": "Bluetooth Auth Agent",
            }
        ]
    }

    app.dependency_overrides[verify_auth_wrapper] = _allow
    try:
        with TestClient(app) as client:
            with patch.object(
                system_api.system_service, "get_failed_services", return_value=payload
            ):
                response = client.get("/api/v1/system/services/failed")
    finally:
        app.dependency_overrides.pop(verify_auth_wrapper, None)

    assert response.status_code == 200
    assert response.json()["units"][0]["unit"] == "bt-agent.service"


def test_api_set_ntp_disables():
    async def _allow():
        return True

    payload = {
        "synchronized": False,
        "ntp_service": False,
        "server_name": None,
        "server_address": None,
        "fallback_servers": [],
        "runtime_servers": [],
        "poll_interval": None,
        "frequency": None,
        "source": "unknown",
    }

    app.dependency_overrides[verify_auth_wrapper] = _allow
    try:
        with TestClient(app) as client:
            with patch.object(
                system_api.system_service, "set_ntp_enabled", return_value=payload
            ) as set_ntp:
                response = client.post("/api/v1/system/ntp", json={"enabled": False})
    finally:
        app.dependency_overrides.pop(verify_auth_wrapper, None)

    assert response.status_code == 200
    set_ntp.assert_called_once_with(False)
    assert response.json()["ntp_service"] is False
