"""Concurrency checks for system API handlers."""

from __future__ import annotations

import asyncio
import threading

import pytest

from wlanpi_core.api.api_v1.endpoints import system_api


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
