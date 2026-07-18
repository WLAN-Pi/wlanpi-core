"""Concurrency-boundary checks for read-only network API handlers."""

from unittest.mock import AsyncMock

import pytest

from wlanpi_core.api.api_v1.endpoints import network_api, network_info_api


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "worker", "kwargs"),
    [
        (
            network_api.show_routing_table,
            network_api.network_primitives.get_routing_table,
            {"namespace": "scan"},
        ),
        (
            network_api.show_tcp_connections,
            network_api.network_primitives.get_tcp_connections,
            {"namespace": "scan"},
        ),
        (
            network_api.show_udp_connections,
            network_api.network_primitives.get_udp_connections,
            {"namespace": "scan"},
        ),
        (
            network_api.show_dhcp_leases,
            network_api.network_primitives.get_dhcp_leases,
            {},
        ),
        (
            network_api.show_interface_link_stats,
            network_api._read_interface_link_stats,
            {"iface": "eth0"},
        ),
    ],
)
async def test_network_handler_offloads_sync_worker(
    mocker,
    handler,
    worker,
    kwargs,
):
    to_thread = mocker.patch.object(
        network_api.asyncio,
        "to_thread",
        new=AsyncMock(return_value={}),
    )

    assert await handler(**kwargs) == {}
    to_thread.assert_awaited_once_with(worker, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "worker", "handler_kwargs", "worker_kwargs"),
    [
        (
            network_info_api.show_network_info,
            network_info_api.network_info_service.show_info,
            {},
            {},
        ),
        (
            network_info_api.show_public_ip6,
            network_info_api.network_info_service.show_publicip,
            {},
            {"ip_version": 6},
        ),
    ],
)
async def test_network_info_handler_offloads_sync_worker(
    mocker,
    handler,
    worker,
    handler_kwargs,
    worker_kwargs,
):
    to_thread = mocker.patch.object(
        network_info_api.asyncio,
        "to_thread",
        new=AsyncMock(return_value={}),
    )

    assert await handler(**handler_kwargs) == {}
    to_thread.assert_awaited_once_with(worker, **worker_kwargs)
