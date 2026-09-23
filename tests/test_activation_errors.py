"""Activation errors carry detail (review of #298, issue #293)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    JOSH_THREE_RADIO,
    live_adapter_inventory_mocks,
    write_json_config,
)
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
                    "mlo": False,
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
