import logging

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.services import network_service

router = APIRouter()

API_DEFAULT_TIMEOUT = 20

log = logging.getLogger("uvicorn")


@router.get("/wlan/getInterfaces", response_model=network.Interfaces)
async def get_a_systemd_network_interfaces(timeout: int = API_DEFAULT_TIMEOUT):
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.get_systemd_network_interfaces(timeout)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/wlan/scan", response_model=network.ScanResults, response_model_exclude_none=True
)
async def get_a_systemd_network_scan(
    type: str, interface: str, timeout: int = API_DEFAULT_TIMEOUT
):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """

    try:
        # return await network_service.get_systemd_network_scan(type)
        return await network_service.get_async_systemd_network_scan(
            type, interface, timeout
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post("/wlan/set", response_model=network.NetworkSetupStatus)
async def set_a_systemd_network(
    setup: network.WlanInterfaceSetup, timeout: int = API_DEFAULT_TIMEOUT
):
    """
    Queries systemd via dbus to set a single network.
    """

    try:
        return await network_service.set_systemd_network_addNetwork(
            setup.interface, setup.netConfig, setup.removeAllFirst, timeout
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/wlan/getConnected",
    response_model=network.ConnectedNetwork,
    response_model_exclude_none=True,
)
async def get_a_systemd_currentNetwork_details(
    interface: str, timeout: int = API_DEFAULT_TIMEOUT
):
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.get_systemd_network_currentNetwork_details(
            interface, timeout
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
