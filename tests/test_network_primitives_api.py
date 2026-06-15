"""API-level tests for P0 network primitive endpoints."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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


def test_api_get_network_routing(client):
    routes = [{"dst": "default", "gateway": "10.10.0.254", "dev": "eth0"}]
    with patch(
        "wlanpi_core.network.routing.ns_exec",
        return_value=MagicMock(stdout=json.dumps(routes)),
    ):
        response = client.get("/api/v1/network/routing")
    assert response.status_code == 200
    body = response.json()
    assert body["routes"] == routes


def test_api_get_network_connections_tcp(client):
    with patch(
        "wlanpi_core.network.connections.ns_exec",
        return_value=MagicMock(stdout="ESTAB 0 0 10.0.0.1:22 10.0.0.2:50115\n"),
    ):
        response = client.get("/api/v1/network/connections/tcp")
    assert response.status_code == 200
    body = response.json()
    assert body["connections"][0]["protocol"] == "tcp"


def test_api_get_network_connections_udp(client):
    with patch(
        "wlanpi_core.network.connections.ns_exec",
        return_value=MagicMock(stdout="UNCONN 0 0 0.0.0.0:68 0.0.0.0:*\n"),
    ):
        response = client.get("/api/v1/network/connections/udp")
    assert response.status_code == 200
    body = response.json()
    assert body["connections"][0]["protocol"] == "udp"


def test_api_get_network_dhcp_leases(client):
    with patch(
        "wlanpi_core.network.get_dhcp_leases",
        return_value={
            "leases": [{"interface": "eth0", "fixed_address": "10.10.0.163"}],
            "source": "/var/lib/dhcp",
        },
    ):
        response = client.get("/api/v1/network/dhcp/leases")
    assert response.status_code == 200
    body = response.json()
    assert body["leases"][0]["interface"] == "eth0"


def test_api_get_network_link_stats(client):
    stats = {
        "interface": "eth0",
        "namespace": None,
        "link_detected": "yes",
        "speed_mbps": 1000,
        "duplex": "Full",
        "port": None,
        "driver": "bcmgenet",
        "raw": {"speed": "1000Mb/s"},
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.network_api.resolve_interface_namespace",
        return_value=None,
    ):
        with patch(
            "wlanpi_core.network.get_link_stats",
            return_value=stats,
        ):
            response = client.get("/api/v1/network/interfaces/eth0/link-stats")
    assert response.status_code == 200
    body = response.json()
    assert body["interface"] == "eth0"
    assert body["speed_mbps"] == 1000


def test_api_post_network_dhcp_renew(client):
    with patch(
        "wlanpi_core.network.renew_interface_dhcp",
        return_value={
            "interface": "eth0",
            "namespace": None,
            "status": "renewed",
        },
    ):
        response = client.post("/api/v1/network/interfaces/eth0/renew")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "renewed"
    assert body["interface"] == "eth0"


def test_api_get_network_wlan_usb_drivers(client):
    with patch(
        "wlanpi_core.network.get_usb_wlan_drivers",
        return_value={
            "adapters": [
                {"interface": "wlan0", "driver": "ath9k_htc", "bus": "usb"},
            ],
            "interfaces_scanned": 2,
        },
    ):
        response = client.get("/api/v1/network/wlan/usb-drivers")
    assert response.status_code == 200
    body = response.json()
    assert body["adapters"][0]["bus"] == "usb"


def test_api_get_network_wlan_pci_drivers(client):
    with patch(
        "wlanpi_core.network.get_pci_wlan_drivers",
        return_value={
            "adapters": [
                {"interface": "wlanpi0", "driver": "brcmfmac", "bus": "pci"},
            ],
            "pci_devices": [
                {"pci_id": "0000:01:00.0", "description": "Wireless controller"},
            ],
            "interfaces_scanned": 2,
        },
    ):
        response = client.get("/api/v1/network/wlan/pci-drivers")
    assert response.status_code == 200
    body = response.json()
    assert body["adapters"][0]["bus"] == "pci"
    assert body["pci_devices"][0]["pci_id"] == "0000:01:00.0"
