"""Tests for WLAN_MANAGEMENT=auto|manual (core leaves Wi-Fi to the operator)."""

import asyncio

import pytest
from fastapi import HTTPException

from wlanpi_core.api.api_v1.endpoints import network_api, network_config_api
from wlanpi_core.core.config import Settings, settings
from wlanpi_core.core.mode_guard import require_wlan_management_enabled
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.system.system import DeviceInfo


def test_default_is_auto():
    assert Settings().WLAN_MANAGEMENT == "auto"


def test_manual_is_accepted():
    assert Settings(WLAN_MANAGEMENT="manual").WLAN_MANAGEMENT == "manual"


def test_value_is_normalized():
    assert Settings(WLAN_MANAGEMENT="  MANUAL ").WLAN_MANAGEMENT == "manual"


def test_invalid_value_falls_back_to_auto():
    # Startup must never fail on a bad value; fall back to auto.
    assert Settings(WLAN_MANAGEMENT="bogus").WLAN_MANAGEMENT == "auto"


def test_guard_is_noop_when_auto(monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "auto")
    require_wlan_management_enabled()


def test_guard_raises_409_when_manual(monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "manual")
    with pytest.raises(ValidationError) as exc:
        require_wlan_management_enabled()
    assert exc.value.status_code == 409


def test_activate_rejected_when_manual(monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "manual")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(network_config_api.activate_config("lab_cfg"))
    assert exc.value.status_code == 409


def test_deactivate_rejected_when_manual(monkeypatch):
    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "manual")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(network_config_api.deactivate_config("lab_cfg"))
    assert exc.value.status_code == 409


def test_revert_rejected_when_manual(monkeypatch):
    class _Req:
        iface = "wlan0"
        namespace = "wlanpi"
        delete_namespace = True

    monkeypatch.setattr(settings, "WLAN_MANAGEMENT", "manual")
    response = asyncio.run(network_api.revert_wlan_namespace(_Req()))
    assert response.status_code == 409


def test_device_info_schema_has_wlan_management():
    assert "wlan_management" in DeviceInfo.model_fields
