import asyncio
from unittest.mock import AsyncMock

from wlanpi_core.api.api_v1.endpoints import network_config_api
from wlanpi_core.schemas.network.network import (
    ActivationResponse,
    AdapterOutcome,
    DeactivationResponse,
)
from wlanpi_core.utils import network_config


def test_get_status_uses_to_thread(mocker):
    to_thread = mocker.patch.object(
        network_config_api.asyncio,
        "to_thread",
        new=AsyncMock(return_value={"root": {}}),
    )

    result = asyncio.run(network_config_api.get_status())

    to_thread.assert_awaited_once_with(network_config.status)
    assert result == {"root": {}}


def test_get_configs_uses_to_thread(mocker):
    to_thread = mocker.patch.object(
        network_config_api.asyncio,
        "to_thread",
        new=AsyncMock(return_value={"lab_cfg": False}),
    )

    result = asyncio.run(network_config_api.get_configs())

    to_thread.assert_awaited_once_with(network_config.list_configs)
    assert result == {"lab_cfg": False}


def test_activate_config_uses_to_thread(mocker):
    outcome = AdapterOutcome(interface="wlan0", status="provisioned")
    to_thread = mocker.patch.object(
        network_config_api.asyncio,
        "to_thread",
        new=AsyncMock(return_value=(True, [outcome])),
    )

    result = asyncio.run(
        network_config_api.activate_config("lab_cfg", override_active=True)
    )

    to_thread.assert_awaited_once_with(
        network_config.activate_config_report, "lab_cfg", True
    )
    assert result == ActivationResponse(
        id="lab_cfg",
        message="Configuration activated successfully",
        outcomes=[outcome],
    )


def test_deactivate_config_uses_to_thread(mocker):
    to_thread = mocker.patch.object(
        network_config_api.asyncio,
        "to_thread",
        new=AsyncMock(side_effect=[True, []]),
    )

    result = asyncio.run(
        network_config_api.deactivate_config("lab_cfg", override_active=True)
    )

    assert to_thread.await_args_list[0] == mocker.call(
        network_config.deactivate_config,
        "lab_cfg",
        override_active=True,
    )
    assert to_thread.await_args_list[1] == mocker.call(network_config.left_alone)
    assert result == DeactivationResponse(
        id="lab_cfg", message="Configuration deactivated successfully", left_alone=[]
    )


def test_deactivate_config_normalizes_override_active(mocker):
    to_thread = mocker.patch.object(
        network_config_api.asyncio,
        "to_thread",
        new=AsyncMock(side_effect=[True, []]),
    )

    asyncio.run(network_config_api.deactivate_config("lab_cfg", override_active=False))

    to_thread.assert_any_await(
        network_config.deactivate_config,
        "lab_cfg",
        override_active=False,
    )
