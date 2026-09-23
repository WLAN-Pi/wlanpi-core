"""Scenario handlers for p0_api_test_matrix.csv rows.

Mocking policy: stub adapter enumeration only for hardware layout rows;
stub run_command for CLI wrappers; keep FastAPI routing and auth real.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import (
    JOSH_THREE_RADIO,
    live_adapter_inventory_mocks,
    write_json_config,
)
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
    with patch(
        "wlanpi_core.services.system_service.restart_service", return_value=True
    ):
        with patch(
            "wlanpi_core.services.system_service.is_allowed_service", return_value=True
        ):
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


def _static_device_info():
    """Stub the cached model/hostname lookup, which runs wlanpi-model and hostname."""
    return patch(
        "wlanpi_core.api.api_v1.endpoints.system_api._read_static_device_info",
        return_value={
            "model": "WLAN Pi R4",
            "hostname": "wlanpi-test.local",
            "name": "wlanpi-test",
            "software_version": "3.0.0",
        },
    )


def handle_system_device_info_any_mode(client, auth_headers, scenario):
    with _static_device_info():
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
        "DNS Server 1 Resolution": "9.9.9.9: OK",
        "Arping Gateway": "1ms",
        "custom": [],
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_reachability",
        new=AsyncMock(return_value={"results": reachability_results}),
    ):
        response = client.get("/api/v1/utils/reachability")
    _expect_status(response, scenario.expected_http)


def handle_utils_reachability_custom_targets(client, auth_headers, scenario):
    from unittest.mock import AsyncMock

    reachability_results = {
        "Ping Google": "1ms",
        "Browse Google": "OK",
        "Ping Gateway": "1ms",
        "Arping Gateway": "1ms",
        "custom": [
            {
                "target": "8.8.8.8",
                "success": True,
                "rttMsMin": 5.0,
                "rttMsAvg": 5.0,
                "rttMsMax": 5.0,
                "packetLossPercent": 0.0,
                "display": "5.0ms",
            }
        ],
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_reachability",
        new=AsyncMock(return_value={"results": reachability_results}),
    ) as reach:
        response = client.get(
            "/api/v1/utils/reachability",
            params={"targets": "8.8.8.8"},
        )
    _expect_status(response, scenario.expected_http)
    reach.assert_awaited_once_with(targets=["8.8.8.8"])
    assert response.json()["custom"][0]["target"] == "8.8.8.8"


def handle_utils_speedtest(client, auth_headers, scenario):
    from unittest.mock import AsyncMock

    payload = {
        "results": {
            "ipAddress": "1.2.3.4",
            "downloadSpeed": "100.00 Mbps",
            "uploadSpeed": "50.00 Mbps",
            "pingMs": 5.0,
            "jitterMs": 0.0,
            "server": "Test Server",
            "testedAt": "2026-06-14T17:38:48+00:00",
        }
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.utils_api.utils_service.show_speedtest",
        new=AsyncMock(return_value=payload),
    ):
        response = client.get("/api/v1/utils/speedtest")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["downloadSpeed"]


def handle_reg_domain_list(client, auth_headers, scenario):
    response = client.get("/api/v1/system/reg-domain/list")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    countries = body["countries"]
    assert len(countries) > 9
    codes = [country["code"] for country in countries]
    assert len(codes) == len(set(codes))
    assert all(len(code) == 2 and code.isalpha() and code.isupper() for code in codes)
    assert all(country["name"] for country in countries)


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
        new=AsyncMock(
            return_value={
                "interface": "eth0",
                "namespace": None,
                "status": "renewed",
            }
        ),
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
            "interfaces_scanned": 2,
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
            "interfaces_scanned": 2,
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
    status = {
        "root": {
            "wlanpi0": {"type": "monitor"},
            "wlan0": {"type": "managed"},
        }
    }
    with patch("wlanpi_core.wlan.scan.network_config.status", return_value=status):
        with patch(
            "wlanpi_core.wpa.scan.run_interface_scan",
            return_value=_sample_networks(),
        ) as run_scan:
            response = client.get("/api/v1/utils/wlan/scan")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["selectedAdapter"]["iface"] == "wlan0"
    assert body["networks"]
    run_scan.assert_called_once()
    assert run_scan.call_args.args[0] == "wlan0"


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


def handle_network_config_activate_stale_phy_mismatch(
    client, auth_headers, scenario, netcfg_env
):
    write_json_config(
        netcfg_env["cfg_dir"],
        "stale_phy_cfg",
        {
            "id": "stale_phy_cfg",
            "namespaces": [],
            "roots": [
                {
                    "mode": "monitor",
                    "iface_display_name": "wlan1",
                    "phy": "phy1",
                    "interface": "wlan1",
                    "security": None,
                    "mlo": False,
                    "default_route": False,
                    "autostart_app": None,
                }
            ],
        },
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        response = client.post(
            "/api/v1/network/config/activate/stale_phy_cfg",
            params={"override_active": True},
        )
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["id"] == "stale_phy_cfg"
    assert body["message"] == "Configuration activated successfully"
    assert [(o["interface"], o["status"]) for o in body["outcomes"]] == [
        ("wlan1", "connected")
    ]
    assert inventory.adds == [("phy2", "wlan1", None)]
    assert inventory.live() == {
        "wlan0": ("phy0", None, "managed"),
        "wlan1": ("phy2", None, "monitor"),
        "wlan2": ("phy1", None, "managed"),
    }
    assert netcfg_env["ccf"].read_text().strip() == "stale_phy_cfg"


def handle_network_config_activate_default_single_radio(
    client, auth_headers, scenario, netcfg_env
):
    single = {"wlan0": {"phy": "phy0", "mac": "00:11:22:33:44:00"}}
    with live_adapter_inventory_mocks(single) as inventory:
        response = client.post(
            "/api/v1/network/config/activate/default",
            params={"override_active": True},
        )
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["message"] == "Configuration activated successfully"
    assert [(o["interface"], o["status"]) for o in body["outcomes"]] == [
        ("wlan0", "connected")
    ]
    assert inventory.live() == {"wlan0": ("phy0", None, "managed")}
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_network_config_create_snapshots_mac(
    client, auth_headers, scenario, netcfg_env
):
    payload = {
        "id": "pin_wlan1",
        "namespaces": [],
        "roots": [
            {
                "mode": "managed",
                "iface_display_name": "wlan1",
                "phy": "phy1",
                "interface": "wlan1",
                "security": None,
                "mlo": False,
                "default_route": False,
                "autostart_app": None,
            }
        ],
    }
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        created = client.post("/api/v1/network/config/", json=payload)
        fetched = client.get("/api/v1/network/config/pin_wlan1")
    _expect_status(created, "200")
    _expect_status(fetched, scenario.expected_http)
    mac = fetched.json()["roots"][0].get("mac")
    expected = JOSH_THREE_RADIO["wlan1"]["mac"]
    assert mac == expected, (
        f"#237: POST /network/config/ did not snapshot live MAC; "
        f"got {mac!r}, expected {expected}"
    )


def handle_network_config_change_busy_409(client, auth_headers, scenario, netcfg_env):
    from wlanpi_core.utils import network_config as nc

    write_json_config(
        netcfg_env["cfg_dir"],
        "busy_cfg",
        {"id": "busy_cfg", "namespaces": [], "roots": []},
    )
    with nc.network_change_lock():
        responses = [
            client.post(
                "/api/v1/network/config/activate/busy_cfg",
                params={"override_active": True},
            ),
            client.post(
                "/api/v1/network/config/deactivate/busy_cfg",
                params={"override_active": True},
            ),
            client.post(
                "/api/v1/network/wlan/revert",
                json={"iface": "wlan0", "namespace": "ns_a", "delete_namespace": True},
            ),
        ]
    for response in responses:
        _expect_status(response, scenario.expected_http)
        assert "in progress" in response.text
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_network_config_reserved_ids_400(client, auth_headers, scenario, netcfg_env):
    for cfg_id in ("Default", "STATUS", "root"):
        response = client.post(
            "/api/v1/network/config/",
            json={"id": cfg_id, "namespaces": [], "roots": []},
        )
        _expect_status(response, scenario.expected_http)
        assert "reserved" in response.json()["detail"]
    assert sorted(p.name for p in netcfg_env["cfg_dir"].iterdir()) == []


def handle_network_config_create_invalid_psk_422(
    client, auth_headers, scenario, netcfg_env
):
    def payload(security, psk):
        return {
            "id": "psk_cfg",
            "namespaces": [],
            "roots": [
                {
                    "mode": "managed",
                    "iface_display_name": "wlan0",
                    "phy": "phy0",
                    "interface": "wlan0",
                    "security": {"ssid": "Net", "security": security, "psk": psk},
                    "mlo": False,
                    "default_route": False,
                    "autostart_app": None,
                }
            ],
        }

    for security, psk in (("WPA2-PSK", "abc"), ("WPA3-PSK", "a" * 64)):
        response = client.post("/api/v1/network/config/", json=payload(security, psk))
        _expect_status(response, scenario.expected_http)
        assert "psk must be 8-63 printable ASCII" in response.text
    assert not (netcfg_env["cfg_dir"] / "psk_cfg.json").exists()


def handle_network_config_secrets_not_returned(
    client, auth_headers, scenario, netcfg_env
):
    import json as _json

    entry = {
        "mode": "managed",
        "iface_display_name": "wlan0",
        "phy": "phy0",
        "interface": "wlan0",
        "security": {"ssid": "Net", "security": "WPA2-PSK", "psk": "first-passphrase"},
        "mlo": False,
        "default_route": False,
        "autostart_app": None,
    }
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        created = client.post(
            "/api/v1/network/config/",
            json={"id": "sec_cfg", "namespaces": [], "roots": [entry]},
        )
        _expect_status(created, "200")
        path = netcfg_env["cfg_dir"] / "sec_cfg.json"

        fetched = client.get("/api/v1/network/config/sec_cfg")
        _expect_status(fetched, scenario.expected_http)
        security = fetched.json()["roots"][0]["security"]
        assert "psk" not in security and security["psk_set"] is True
        assert "first-passphrase" not in fetched.text

        # Edit something else and send the entry back as GET returned it.
        returned = fetched.json()["roots"][0]
        returned["mode"] = "monitor"
        patched = client.patch(
            "/api/v1/network/config/sec_cfg", json={"roots": [returned]}
        )
        _expect_status(patched, scenario.expected_http)
        assert "first-passphrase" not in patched.text
        stored = _json.loads(path.read_text())["roots"][0]
        assert stored["mode"] == "monitor"
        assert stored["security"]["psk"] == "first-passphrase"

        # A new psk in the PATCH replaces the stored one.
        returned["security"]["psk"] = "second-passphrase"
        _expect_status(
            client.patch("/api/v1/network/config/sec_cfg", json={"roots": [returned]}),
            "200",
        )
        assert (
            _json.loads(path.read_text())["roots"][0]["security"]["psk"]
            == "second-passphrase"
        )
    assert path.stat().st_mode & 0o777 == 0o600


def _root_entry(interface, phy, security=None):
    return {
        "mode": "managed",
        "iface_display_name": interface,
        "phy": phy,
        "interface": interface,
        "security": security,
        "mlo": False,
        "default_route": False,
        "autostart_app": None,
    }


def handle_network_config_activate_invalid_entry_422(
    client, auth_headers, scenario, netcfg_env
):
    # WPA2 without a psk passes the schema but fails activation validation.
    write_json_config(
        netcfg_env["cfg_dir"],
        "nopsk_cfg",
        {
            "id": "nopsk_cfg",
            "namespaces": [],
            "roots": [
                _root_entry("wlan0", "phy0", {"ssid": "Net", "security": "WPA2-PSK"})
            ],
        },
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO):
        response = client.post(
            "/api/v1/network/config/activate/nopsk_cfg",
            params={"override_active": True},
        )
    _expect_status(response, scenario.expected_http)
    detail = response.json()["detail"]
    assert detail["message"] == "Configuration is invalid"
    [outcome] = detail["outcomes"]
    assert outcome["interface"] == "wlan0" and outcome["invalid"] is True
    assert "psk is required" in outcome["detail"]
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_network_config_activate_fault_500_outcomes(
    client, auth_headers, scenario, netcfg_env
):
    write_json_config(
        netcfg_env["cfg_dir"],
        "fault_cfg",
        {
            "id": "fault_cfg",
            "namespaces": [{**_root_entry("wlan1", "phy2"), "namespace": "bad_ns"}],
            "roots": [_root_entry("wlan2", "phy1")],
        },
    )
    faults = {
        (None, ("iw", "phy#2", "set", "netns", "name", "bad_ns")): (
            "command failed: Operation not supported (-95)\n"
        )
    }
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO, faults=faults) as inventory:
        response = client.post(
            "/api/v1/network/config/activate/fault_cfg",
            params={"override_active": True},
        )
    _expect_status(response, scenario.expected_http)
    detail = response.json()["detail"]
    assert detail["message"] == "Failed to activate configuration"
    statuses = {
        (o["namespace"], o["interface"]): o["status"] for o in detail["outcomes"]
    }
    assert statuses == {("bad_ns", "wlan1"): "error", (None, "wlan2"): "connected"}
    assert not any(o["invalid"] for o in detail["outcomes"])
    assert inventory.live()["wlan1"] == ("phy2", None, "managed")
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_wlan_revert_reverts_all(client, auth_headers, scenario, netcfg_env):
    write_json_config(
        netcfg_env["cfg_dir"],
        "two_ns",
        {
            "id": "two_ns",
            "namespaces": [
                {**_root_entry("wlan1", "phy2"), "namespace": "ns_a"},
                {**_root_entry("wlan2", "phy1"), "namespace": "ns_b"},
            ],
            "roots": [],
        },
    )
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        activated = client.post(
            "/api/v1/network/config/activate/two_ns", params={"override_active": True}
        )
        _expect_status(activated, "200")
        # iface/namespace name only one of them; revert is documented as revert-all.
        response = client.post(
            "/api/v1/network/wlan/revert",
            json={"iface": "wlan1", "namespace": "ns_a", "delete_namespace": False},
        )
    _expect_status(response, scenario.expected_http)
    assert response.json() == {
        "success": True,
        "message": "Reverted every Core namespace to root; the default configuration is active.",
    }
    assert not inventory.netns
    assert inventory.live() == {
        "wlan0": ("phy0", None, "managed"),
        "wlan1": ("phy2", None, "managed"),
        "wlan2": ("phy1", None, "managed"),
    }
    assert netcfg_env["ccf"].read_text().strip() == "default"


def handle_wlan_management_settings_parse(client, auth_headers, scenario):
    from wlanpi_core.core.config import Settings

    assert Settings().WLAN_MANAGEMENT == "auto"
    assert Settings(WLAN_MANAGEMENT="manual").WLAN_MANAGEMENT == "manual"
    assert Settings(WLAN_MANAGEMENT="  MANUAL ").WLAN_MANAGEMENT == "manual"
    assert Settings(WLAN_MANAGEMENT="bogus").WLAN_MANAGEMENT == "auto"


def handle_system_device_info_wlan_management(client, auth_headers, scenario):
    from wlanpi_core.core.config import settings

    with _static_device_info():
        with patch.object(settings, "WLAN_MANAGEMENT", "manual"):
            response = client.get("/api/v1/system/device/info")
        _expect_status(response, scenario.expected_http)
        body = response.json()
        assert body["wlan_management"] == "manual"

        with patch.object(settings, "WLAN_MANAGEMENT", "auto"):
            response = client.get("/api/v1/system/device/info")
    assert response.json()["wlan_management"] == "auto"


def handle_wlan_management_manual_activate_409(client, auth_headers, scenario):
    from wlanpi_core.core.config import settings

    with patch.object(settings, "WLAN_MANAGEMENT", "manual"):
        response = client.post("/api/v1/network/config/activate/lab_cfg")
    _expect_status(response, scenario.expected_http)
    detail = response.json().get("detail", "")
    assert "WLAN_MANAGEMENT=manual" in detail


def handle_wlan_management_manual_deactivate_409(client, auth_headers, scenario):
    from wlanpi_core.core.config import settings

    with patch.object(settings, "WLAN_MANAGEMENT", "manual"):
        response = client.post("/api/v1/network/config/deactivate/lab_cfg")
    _expect_status(response, scenario.expected_http)
    detail = response.json().get("detail", "")
    assert "WLAN_MANAGEMENT=manual" in detail


def handle_wlan_management_manual_revert_409(client, auth_headers, scenario):
    from wlanpi_core.core.config import settings

    with patch.object(settings, "WLAN_MANAGEMENT", "manual"):
        response = client.post(
            "/api/v1/network/wlan/revert",
            json={
                "iface": "wlan0",
                "namespace": "lab_ns",
                "delete_namespace": True,
            },
        )
    _expect_status(response, scenario.expected_http)
    assert "WLAN_MANAGEMENT=manual" in response.text


def handle_system_ntp_get(client, auth_headers, scenario):
    payload = {
        "synchronized": False,
        "ntp_service": True,
        "server_name": "2.debian.pool.ntp.org",
        "server_address": "192.168.2.123",
        "fallback_servers": ["0.debian.pool.ntp.org"],
        "runtime_servers": [],
        "poll_interval": "32s",
        "frequency": -1234,
        "source": "default",
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.system_api.system_service.get_ntp",
        return_value=payload,
    ):
        response = client.get("/api/v1/system/ntp")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["ntp_service"] is True
    assert body["source"] == "default"
    assert body["server_name"] == "2.debian.pool.ntp.org"


def handle_system_ntp_set(client, auth_headers, scenario):
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
    with patch(
        "wlanpi_core.api.api_v1.endpoints.system_api.system_service.set_ntp_enabled",
        return_value=payload,
    ) as set_ntp:
        response = client.post("/api/v1/system/ntp", json={"enabled": False})
    _expect_status(response, scenario.expected_http)
    set_ntp.assert_called_once_with(False)
    assert response.json()["ntp_service"] is False


def handle_system_health(client, auth_headers, scenario):
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
    with patch(
        "wlanpi_core.api.api_v1.endpoints.system_api.system_service.get_health",
        return_value=payload,
    ):
        response = client.get("/api/v1/system/health")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["ntp"]["enabled"] is True
    assert body["temperatures"][0]["celsius"] == 60.0
    assert "throttled" in body
    assert "load" in body
    assert "swap" in body
    assert "rfkill" in body


def handle_system_services_failed(client, auth_headers, scenario):
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
    with patch(
        "wlanpi_core.api.api_v1.endpoints.system_api.system_service.get_failed_services",
        return_value=payload,
    ):
        response = client.get("/api/v1/system/services/failed")
    _expect_status(response, scenario.expected_http)
    assert response.json()["units"][0]["unit"] == "bt-agent.service"


def handle_wlan_link(client, auth_headers, scenario):
    payload = {
        "interface": "wlan0",
        "namespace": None,
        "connected": True,
        "ssid": "PurpleDove",
        "bssid": "68:51:34:7c:32:13",
        "freq_mhz": 5200.0,
        "signal_dbm": -48.0,
        "rx_bitrate": "286.7 MBit/s HE-MCS 11",
        "tx_bitrate": "286.7 MBit/s HE-MCS 11",
        "rx_bytes": 2112666,
        "tx_bytes": 104496501,
        "raw": "",
    }
    with patch(
        "wlanpi_core.api.api_v1.endpoints.network_api.resolve_interface_namespace",
        return_value=None,
    ):
        with patch("wlanpi_core.network.get_wlan_link", return_value=payload):
            response = client.get("/api/v1/network/interfaces/wlan0/wlan-link")
    _expect_status(response, scenario.expected_http)
    body = response.json()
    assert body["connected"] is True
    assert body["ssid"] == "PurpleDove"


HANDLERS.update(
    {
        "service_restart_orb": handle_service_restart_orb,
        "service_restart_not_allowed": handle_service_restart_not_allowed,
        "publicip6": handle_publicip6,
        "timezone_get_set": handle_timezone_get_set,
        "system_device_info_any_mode": handle_system_device_info_any_mode,
        "utils_reachability_live": handle_utils_reachability_live,
        "utils_reachability_custom_targets": handle_utils_reachability_custom_targets,
        "utils_speedtest": handle_utils_speedtest,
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
        "network_config_activate_stale_phy_mismatch": handle_network_config_activate_stale_phy_mismatch,
        "network_config_activate_default_single_radio": handle_network_config_activate_default_single_radio,
        "network_config_create_snapshots_mac": handle_network_config_create_snapshots_mac,
        "network_config_change_busy_409": handle_network_config_change_busy_409,
        "network_config_reserved_ids_400": handle_network_config_reserved_ids_400,
        "network_config_create_invalid_psk_422": handle_network_config_create_invalid_psk_422,
        "network_config_secrets_not_returned": handle_network_config_secrets_not_returned,
        "network_config_activate_invalid_entry_422": handle_network_config_activate_invalid_entry_422,
        "network_config_activate_fault_500_outcomes": handle_network_config_activate_fault_500_outcomes,
        "wlan_revert_reverts_all": handle_wlan_revert_reverts_all,
        "wlan_management_settings_parse": handle_wlan_management_settings_parse,
        "system_device_info_wlan_management": handle_system_device_info_wlan_management,
        "wlan_management_manual_activate_409": handle_wlan_management_manual_activate_409,
        "wlan_management_manual_deactivate_409": handle_wlan_management_manual_deactivate_409,
        "wlan_management_manual_revert_409": handle_wlan_management_manual_revert_409,
        "system_ntp_get": handle_system_ntp_get,
        "system_ntp_set": handle_system_ntp_set,
        "system_health": handle_system_health,
        "system_services_failed": handle_system_services_failed,
        "wlan_link": handle_wlan_link,
    }
)


def run_api_scenario(
    scenario: ApiScenario, client, auth_headers, netcfg_env=None
) -> None:
    handler = HANDLERS.get(scenario.name)
    if handler is None:
        raise KeyError(f"No handler for {scenario.name}")
    kwargs = {}
    if "netcfg_env" in inspect.signature(handler).parameters:
        kwargs["netcfg_env"] = netcfg_env
    handler(client, auth_headers, scenario, **kwargs)
