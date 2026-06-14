"""Scenario handlers for p0_api_test_matrix.csv rows.

Mocking policy: stub adapter enumeration only for hardware layout rows;
stub run_command for CLI wrappers; keep FastAPI routing and auth real.
"""
from __future__ import annotations

from typing import Callable
from unittest.mock import MagicMock, patch

from tests.scenarios.p0_loader import ApiScenario

# scenario name → handler(client, auth_headers, scenario)
HANDLERS: dict[str, Callable] = {}


def _expect_status(response, expected: str) -> None:
    if " or " in expected:
        codes = {int(code.strip()) for code in expected.split(" or ")}
        assert response.status_code in codes
    elif "/" in expected:
        assert response.status_code in {int(code) for code in expected.split("/")}
    else:
        assert response.status_code == int(expected)


def handle_service_restart_orb(client, auth_headers, scenario):
    with patch("wlanpi_core.services.system_service.restart_service", return_value=True):
        with patch("wlanpi_core.services.system_service.is_allowed_service", return_value=True):
            response = client.post("/api/v1/system/service/restart?name=orb")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["name"] == "orb"
    assert body["active"] is True


def handle_service_restart_not_allowed(client, auth_headers, scenario):
    response = client.post("/api/v1/system/service/restart?name=evil")
    _expect_status(response, scenario.expected_http)


def handle_publicip6(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.services.network_info_service.run_command",
        return_value=type("R", (), {"stdout": "2001:db8::1\n"})(),
    ):
        response = client.get("/api/v1/network/info/publicip6")
    _expect_status(response, scenario.expected_http)
    assert "info" in response.json()


def handle_timezone_get_set(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.services.system_service.run_command",
        return_value=type("R", (), {"stdout": "Europe/London\n"})(),
    ):
        with patch("wlanpi_core.services.system_service.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            get_resp = client.get("/api/v1/system/timezone")
            assert get_resp.status_code == 200
            with patch(
                "wlanpi_core.services.system_service.set_timezone",
                return_value={"timezone": "Europe/London"},
            ):
                set_resp = client.post(
                    "/api/v1/system/timezone/set",
                    json={"timezone": "Europe/London"},
                )
    assert set_resp.status_code == 200
    assert set_resp.json()["timezone"] == "Europe/London"


def handle_system_device_info_any_mode(client, auth_headers, scenario):
    response = client.get("/api/v1/system/device/info")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert "mode" in body
    assert "hostname" in body


def handle_utils_reachability_live(client, auth_headers, scenario):
    from unittest.mock import AsyncMock

    reachability_results = {
        "Ping Google": "1ms",
        "Browse Google": "OK",
        "Ping Gateway": "1ms",
        "Arping Gateway": "1ms",
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_reachability",
        new=AsyncMock(return_value={"results": reachability_results}),
    ):
        response = client.get("/api/v1/utils/reachability")
    _expect_status(response, scenario.expected_http)


def handle_reg_domain_list(client, auth_headers, scenario):
    response = client.get("/api/v1/system/reg-domain/list")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert len(body["countries"]) == 9
    assert body["countries"][0]["code"]
    assert body["countries"][0]["name"]


def handle_routing_table(client, auth_headers, scenario):
    sample = [{"dst": "default", "gateway": "10.10.0.254", "dev": "eth0"}]
    with patch(
        "wlanpi_core.network.routing.ns_exec",
        return_value=type("R", (), {"stdout": __import__("json").dumps(sample)})(),
    ):
        response = client.get("/api/v1/network/routing")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert "routes" in body
    assert len(body["routes"]) >= 1


def handle_connections_tcp(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.network.connections.ns_exec",
        return_value=MagicMock(stdout="ESTAB 0 0 10.0.0.1:22 10.0.0.2:50115\n"),
    ):
        response = client.get("/api/v1/network/connections/tcp")
    _expect_status(response, scenario.expected_http)
    assert response.json()["connections"][0]["protocol"] == "tcp"


def handle_connections_udp(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.network.connections.ns_exec",
        return_value=MagicMock(stdout="UNCONN 0 0 0.0.0.0:68 0.0.0.0:*\n"),
    ):
        response = client.get("/api/v1/network/connections/udp")
    _expect_status(response, scenario.expected_http)
    assert response.json()["connections"][0]["protocol"] == "udp"


def handle_dhcp_leases(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.network.get_dhcp_leases",
        return_value={
            "leases": [{"interface": "eth0", "fixed_address": "10.10.0.163"}],
            "source": "/var/lib/dhcp",
        },
    ):
        response = client.get("/api/v1/network/dhcp/leases")
    _expect_status(response, scenario.expected_http)
    assert response.json()["leases"][0]["interface"] == "eth0"


def handle_link_stats(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.api.api_v1.endpoints.network_api.resolve_interface_namespace",
        return_value=None,
    ):
        with patch(
            "wlanpi_core.network.get_link_stats",
            return_value={
                "interface": "eth0",
                "namespace": None,
                "link_detected": "yes",
                "speed_mbps": 1000,
                "duplex": "Full",
                "port": None,
                "driver": "bcmgenet",
                "raw": {},
            },
        ):
            response = client.get("/api/v1/network/interfaces/eth0/link-stats")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["interface"] == "eth0"
    assert body["link_detected"] == "yes"


def handle_dhcp_renew(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.network.renew_interface_dhcp",
        return_value={
            "interface": "eth0",
            "namespace": None,
            "status": "renewed",
        },
    ):
        response = client.post("/api/v1/network/interfaces/eth0/renew")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["status"] == "renewed"


def handle_wlan_usb_drivers(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.network.get_usb_wlan_drivers",
        return_value={
            "adapters": [{"interface": "wlan0", "driver": "ath9k_htc", "bus": "usb"}],
        },
    ):
        response = client.get("/api/v1/network/wlan/usb-drivers")
    _expect_status(response, scenario.expected_http)
    assert response.json()["adapters"][0]["bus"] == "usb"


def handle_wlan_pci_drivers(client, auth_headers, scenario):
    with patch(
        "wlanpi_core.network.get_pci_wlan_drivers",
        return_value={
            "adapters": [{"interface": "wlanpi0", "driver": "brcmfmac", "bus": "pci"}],
            "pci_devices": [{"pci_id": "0000:01:00.0", "description": "Wireless"}],
        },
    ):
        response = client.get("/api/v1/network/wlan/pci-drivers")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["adapters"][0]["bus"] == "pci"
    assert body["pci_devices"][0]["pci_id"] == "0000:01:00.0"


def _sample_networks():
    return [
        {
            "ssid": "Test",
            "bssid": "aa:bb:cc:dd:ee:01",
            "signal": -50,
            "freq": 2412,
            "key_mgmt": "wpa-psk",
            "minrate": 1_000_000,
        }
    ]


def handle_scan_auto_single_monitor(client, auth_headers, scenario):
    status = {"root": {"wlanpi0": {"type": "monitor"}}}
    with patch("wlanpi_core.wlan.scan.network_config.status", return_value=status):
        with patch(
            "wlanpi_core.wpa.scan.run_interface_scan",
            return_value=_sample_networks(),
        ):
            response = client.get("/api/v1/utils/wlan/scan")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["selectedAdapter"]["iface"] == "wlanpi0"
    assert body["networks"]


def handle_scan_needs_selection_multi_monitor(client, auth_headers, scenario):
    status = {
        "root": {
            "wlanpi0": {"type": "monitor"},
            "wlanpi1": {"type": "monitor"},
        }
    }
    with patch("wlanpi_core.wlan.scan.network_config.status", return_value=status):
        with patch("wlanpi_core.wpa.scan.run_interface_scan") as run_scan:
            response = client.get("/api/v1/utils/wlan/scan")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    run_scan.assert_not_called()
    assert body["needsSelection"] is True
    assert len(body["candidates"]) == 2
    assert body["networks"] == []


def handle_scan_explicit_iface_namespace(client, auth_headers, scenario):
    status = {
        "root": {"wlanpi0": {"type": "monitor"}},
        "scan_ns": {"wlanpi1": {"type": "monitor"}},
    }
    with patch("wlanpi_core.wlan.scan.network_config.status", return_value=status):
        with patch(
            "wlanpi_core.wpa.scan.run_interface_scan",
            return_value=_sample_networks(),
        ):
            response = client.get(
                "/api/v1/utils/wlan/scan",
                params={"iface": "wlanpi1", "namespace": "scan_ns"},
            )
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["selectedAdapter"]["iface"] == "wlanpi1"
    assert body["selectedAdapter"]["namespace"] == "scan_ns"


def handle_scan_fallback_managed_root(client, auth_headers, scenario):
    status = {"root": {"wlan0": {"type": "managed"}}}
    with patch("wlanpi_core.wlan.scan.network_config.status", return_value=status):
        with patch(
            "wlanpi_core.wpa.scan.run_interface_scan",
            return_value=_sample_networks(),
        ):
            response = client.get("/api/v1/utils/wlan/scan")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["selectedAdapter"]["iface"] == "wlan0"
    assert body["networks"]


def handle_scan_no_adapter(client, auth_headers, scenario):
    status = {"root": {}}
    with patch("wlanpi_core.wlan.scan.network_config.status", return_value=status):
        response = client.get("/api/v1/utils/wlan/scan")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["error"] == "NO_SCAN_ADAPTER"


HANDLERS.update(
    {
        "service_restart_orb": handle_service_restart_orb,
        "service_restart_not_allowed": handle_service_restart_not_allowed,
        "publicip6": handle_publicip6,
        "timezone_get_set": handle_timezone_get_set,
        "system_device_info_any_mode": handle_system_device_info_any_mode,
        "utils_reachability_live": handle_utils_reachability_live,
        "reg_domain_list": handle_reg_domain_list,
        "routing_table": handle_routing_table,
        "connections_tcp": handle_connections_tcp,
        "connections_udp": handle_connections_udp,
        "dhcp_leases": handle_dhcp_leases,
        "link_stats": handle_link_stats,
        "dhcp_renew": handle_dhcp_renew,
        "wlan_usb_drivers": handle_wlan_usb_drivers,
        "wlan_pci_drivers": handle_wlan_pci_drivers,
        "scan_auto_single_monitor": handle_scan_auto_single_monitor,
        "scan_needs_selection_multi_monitor": handle_scan_needs_selection_multi_monitor,
        "scan_explicit_iface_namespace": handle_scan_explicit_iface_namespace,
        "scan_fallback_managed_root": handle_scan_fallback_managed_root,
        "scan_no_adapter": handle_scan_no_adapter,
    }
)


def run_api_scenario(scenario: ApiScenario, client, auth_headers) -> None:
    handler = HANDLERS.get(scenario.name)
    if handler is None:
        raise KeyError(f"No handler for {scenario.name}")
    handler(client, auth_headers, scenario)
