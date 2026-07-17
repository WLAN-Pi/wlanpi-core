"""Concurrency-boundary checks for Wi-Fi API handlers."""

from unittest.mock import AsyncMock

import pytest

from wlanpi_core.api.api_v1.endpoints import wifi_api


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "worker", "kwargs"),
    [
        (wifi_api.show_wifi_capabilities, wifi_api.get_wifi_capabilities, {}),
        (wifi_api.show_wifi_regulatory, wifi_api.get_wifi_regulatory, {}),
        (
            wifi_api.show_hotspot_stations,
            wifi_api.get_hotspot_stations,
            {"iface": "wlan0"},
        ),
        (
            wifi_api.show_hotspot_client_link,
            wifi_api.get_hotspot_client_link,
            {"iface": "wlan0"},
        ),
    ],
)
async def test_wifi_handler_offloads_sync_worker(mocker, handler, worker, kwargs):
    to_thread = mocker.patch.object(
        wifi_api.asyncio,
        "to_thread",
        new=AsyncMock(return_value={}),
    )

    assert await handler(**kwargs) == {}
    to_thread.assert_awaited_once_with(worker, **kwargs)
