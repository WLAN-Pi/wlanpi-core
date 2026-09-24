"""Activation errors carry detail (review of #298, issue #293)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    JOSH_THREE_RADIO,
    live_adapter_inventory_mocks,
    write_json_config,
)
from wlanpi_core.asgi import app
from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.wpa import supplicant

# Captured before any test patches it; conftest mocks the start by default.
_real_start_supplicant = supplicant.start_or_restart_supplicant


@pytest.fixture
def client():
    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(verify_auth_wrapper, None)


def test_driver_refusing_delete_returns_its_error(client, netcfg_env):
    # WLAN Pi R4: brcmfmac refuses `iw dev wlan1 del` with -524.
    write_json_config(
        netcfg_env["cfg_dir"],
        "brcm_cfg",
        {
            "id": "brcm_cfg",
            "namespaces": [],
            "roots": [
                {
                    "mode": "monitor",
                    "iface_display_name": "wlan1",
                    "phy": "phy2",
                    "interface": "wlan1",
                    "security": None,
                    "default_route": False,
                    "autostart_app": None,
                }
            ],
        },
    )
    faults = {
        (
            None,
            ("iw", "dev", "wlan1", "del"),
        ): "command failed: Unknown error 524 (-524)\n"
    }
    with live_adapter_inventory_mocks(JOSH_THREE_RADIO, faults=faults) as inventory:
        response = client.post(
            "/api/v1/network/config/activate/brcm_cfg", params={"override_active": True}
        )
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["message"] == "An adapter command failed"
    assert "-524" in detail["error"]
    assert inventory.live()["wlan1"] == ("phy2", None, "managed")


def test_supplicant_start_failure_returns_its_log_reason(client, netcfg_env):
    # wpa_supplicant 2.12 with -f exits 255 with empty stderr; the reason
    # (here the `mlo=1` Core used to write) is only in its log file.
    write_json_config(
        netcfg_env["cfg_dir"],
        "wpa_cfg",
        {
            "id": "wpa_cfg",
            "namespaces": [],
            "roots": [
                {
                    "mode": "managed",
                    "iface_display_name": "wlan0",
                    "phy": "phy0",
                    "interface": "wlan0",
                    "security": {
                        "ssid": "Net",
                        "security": "WPA2-PSK",
                        "psk": "hunter2-passphrase",
                    },
                }
            ],
        },
    )
    log_lines = [
        "1.0: Successfully initialized wpa_supplicant",
        "1.0: Line 5: failed to parse psk '\"hunter2-passphrase\"'.",
        "1.0: Line 9: unknown network field 'mlo'.",
        "1.0: Line 10: failed to parse network block.",
    ]

    def failing_start(argv, namespace=None):
        Path(argv[argv.index("-f") + 1]).write_text("\n".join(log_lines) + "\n")
        raise RunCommandError("", 255)

    with live_adapter_inventory_mocks(JOSH_THREE_RADIO) as inventory:
        with (
            patch.object(
                supplicant, "start_or_restart_supplicant", new=_real_start_supplicant
            ),
            patch.object(supplicant, "ns_exec", side_effect=failing_start) as start,
        ):
            response = client.post(
                "/api/v1/network/config/activate/wpa_cfg",
                params={"override_active": True},
            )

    start.assert_called_once()
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["message"] == "An adapter command failed"
    assert "wpa_supplicant failed to start for wlan0" in detail["error"]
    assert "unknown network field 'mlo'" in detail["error"]
    assert "hunter2" not in response.text
    assert netcfg_env["ccf"].read_text() == "default"
    assert inventory.live()["wlan0"] == ("phy0", None, "managed")


def test_invalid_entry_is_rejected_before_any_radio_is_touched(
    client, netcfg_env, mocker
):
    # #261: a valid wlan2 entry listed before an invalid wlan0 entry used to be
    # deleted and recreated, then rolled back. Now nothing runs.
    write_json_config(
        netcfg_env["cfg_dir"],
        "bad_261",
        {
            "id": "bad_261",
            "namespaces": [],
            "roots": [
                {
                    "mode": "managed",
                    "iface_display_name": "wlan2",
                    "phy": "phy2",
                    "interface": "wlan2",
                },
                {
                    "mode": "managed",
                    "iface_display_name": "wlan0",
                    "phy": "phy1",
                    "interface": "wlan0",
                    "security": {
                        "security": "WPA2-PSK",
                        "ssid": "nonexistent",
                        "psk": None,
                    },
                },
            ],
        },
    )
    activate = mocker.patch.object(netcfg_env["service"], "activate_config")
    kill = mocker.patch.object(netcfg_env["service"], "kill_all_supplicants")
    teardown = mocker.patch("wlanpi_core.utils.network_config._teardown_profile")

    response = client.post(
        "/api/v1/network/config/activate/bad_261", params={"override_active": True}
    )

    assert response.status_code == 422
    outcomes = response.json()["detail"]["outcomes"]
    assert [o["interface"] for o in outcomes] == ["wlan0"]
    assert outcomes[0]["invalid"] is True
    assert "psk is required" in outcomes[0]["detail"]
    activate.assert_not_called()
    kill.assert_not_called()
    teardown.assert_not_called()
    assert netcfg_env["ccf"].read_text() == "default"

    # Another profile is active: it keeps running and stays current.
    write_json_config(
        netcfg_env["cfg_dir"],
        "other",
        {"id": "other", "namespaces": [], "roots": []},
    )
    netcfg_env["ccf"].write_text("other")
    response = client.post(
        "/api/v1/network/config/activate/bad_261", params={"override_active": True}
    )
    assert response.status_code == 422
    teardown.assert_not_called()
    assert netcfg_env["ccf"].read_text() == "other"

    # The invalid profile is the stored current one (boot, or edited on disk):
    # tear down what may remain of it and repair current.txt.
    netcfg_env["ccf"].write_text("bad_261")
    response = client.post(
        "/api/v1/network/config/activate/bad_261", params={"override_active": True}
    )
    assert response.status_code == 422
    activate.assert_not_called()
    teardown.assert_called_once_with("bad_261")
    assert netcfg_env["ccf"].read_text() == "default"


def test_default_preflight_skips_entries_core_does_not_own(client, netcfg_env, mocker):
    # An unowned default entry is reported skipped even if it would not
    # validate; preflight must not turn it into a 422.
    write_json_config(
        netcfg_env["cfg_dir"],
        "default",
        {
            "id": "default",
            "namespaces": [],
            "roots": [
                {
                    "mode": "managed",
                    "iface_display_name": "wlan0",
                    "phy": "phy0",
                    "interface": "wlan0",
                    "security": {"security": "WPA2-PSK", "ssid": "x", "psk": None},
                }
            ],
        },
    )
    mocker.patch.object(netcfg_env["service"], "is_core_managed", return_value=False)
    # The rest of activation must not reach the host: teardown lists live
    # interfaces with `iw`, and kill_all_supplicants scans /proc and signals.
    teardown = mocker.patch("wlanpi_core.utils.network_config._teardown_profile")
    kill = mocker.patch.object(netcfg_env["service"], "kill_all_supplicants")
    activate = mocker.patch.object(netcfg_env["service"], "activate_config")

    response = client.post(
        "/api/v1/network/config/activate/default", params={"override_active": True}
    )

    assert response.status_code == 200
    assert [o["status"] for o in response.json()["outcomes"]] == ["skipped"]
    activate.assert_not_called()
    teardown.assert_called_once_with("default")
    kill.assert_called_once_with()
    assert netcfg_env["ccf"].read_text() == "default"


def test_invalid_current_profile_resets_current_even_if_teardown_fails(
    client, netcfg_env, mocker
):
    write_json_config(
        netcfg_env["cfg_dir"],
        "bad_261",
        {
            "id": "bad_261",
            "namespaces": [],
            "roots": [
                {
                    "mode": "managed",
                    "iface_display_name": "wlan0",
                    "phy": "phy1",
                    "interface": "wlan0",
                    "security": {"security": "WPA2-PSK", "ssid": "x", "psk": None},
                }
            ],
        },
    )
    netcfg_env["ccf"].write_text("bad_261")
    mocker.patch(
        "wlanpi_core.utils.network_config._teardown_profile",
        side_effect=RuntimeError("revert failed"),
    )

    response = client.post(
        "/api/v1/network/config/activate/bad_261", params={"override_active": True}
    )

    assert response.status_code == 500
    assert netcfg_env["ccf"].read_text() == "default"
