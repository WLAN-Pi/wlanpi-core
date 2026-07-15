"""Concurrency-boundary checks for Bluetooth API handlers."""

from unittest.mock import AsyncMock

import pytest

from wlanpi_core.api.api_v1.endpoints import bluetooth_api


@pytest.mark.asyncio
async def test_bluetooth_status_offloads_sync_worker(mocker):
    expected = {
        "name": "wlanpi",
        "alias": "wlanpi",
        "addr": "00:11:22:33:44:55",
        "power": "On",
        "paired_devices": [],
    }
    to_thread = mocker.patch.object(
        bluetooth_api.asyncio,
        "to_thread",
        new=AsyncMock(return_value=expected),
    )

    assert await bluetooth_api.btstatus() == expected
    to_thread.assert_awaited_once_with(bluetooth_api.bluetooth_service.bluetooth_status)


@pytest.mark.asyncio
async def test_bluetooth_power_offloads_complete_transaction(mocker):
    to_thread = mocker.patch.object(
        bluetooth_api.asyncio,
        "to_thread",
        new=AsyncMock(return_value=True),
    )

    assert await bluetooth_api.bt_power("on") == {
        "status": "success",
        "action": "on",
    }
    to_thread.assert_awaited_once_with(bluetooth_api._set_power_if_present, True)
