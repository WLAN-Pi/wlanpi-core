import logging

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.services import network_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.get("/network/getInterfaces", response_model=network.Interfaces)
async def get_a_systemd_network_interfaces():
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.get_systemd_network_interfaces()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get("/network/scan", response_model=network.ScanResults)
async def get_a_systemd_network_scan(type: str, interface: str):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """

    try:
        # return await network_service.get_systemd_network_scan(type)
        return await network_service.get_async_systemd_network_scan(type, interface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post("/network/set", response_model=network.NetworkSetupStatus)
async def set_a_systemd_network(setup: network.WlanInterfaceSetup):
    """
    Queries systemd via dbus to set a single network.
    """

    try:
        return await network_service.set_systemd_network_addNetwork(
            setup.interface, setup.netConfig, setup.removeAllFirst
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get("/network/getConnected", response_model=network.ConnectedNetwork)
async def get_a_systemd_currentNetwork_details(interface: str):
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.get_systemd_network_currentNetwork_details(
            interface
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
