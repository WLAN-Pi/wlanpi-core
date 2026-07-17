"""Concurrency checks for system API handlers."""

from __future__ import annotations

import asyncio
import threading

import pytest

from wlanpi_core.api.api_v1.endpoints import system_api


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
