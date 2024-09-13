import logging
from typing import Optional, Union

from fastapi import APIRouter, Response

from wlanpi_core.models.network.vlan.vlan_errors import VLANError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.schemas.network.network import IPInterface, IPInterfaceAddress
from wlanpi_core.schemas.network.config import NetworkConfigResponse
from wlanpi_core.services import network_service, network_ethernet_service

router = APIRouter()

API_DEFAULT_TIMEOUT = 20

log = logging.getLogger("uvicorn")


################################
# Ethernet Management          #
################################
@router.get("/ethernet/{interface}", response_model=dict[str, list[IPInterface]])
async def show_all_ethernet_vlans(interface: Optional[str] = None):
    """
    Returns all ethernet interfaces.
    """
    if interface.lower() == "all":
        interface=None

    try:
        return await network_ethernet_service.get_interfaces(interface=interface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except VLANError as ve:
        log.error(ve)
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


################################
# VLAN Management              #
################################

@router.get("/ethernet/all/vlan", response_model=dict[str, list[IPInterface]])
async def show_all_ethernet_vlans():
    """
    Returns all VLANS for all ethernet interfaces.
    """

    try:
        return await network_ethernet_service.get_vlans()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except VLANError as ve:
        log.error(ve)
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get("/ethernet/{interface}/vlan", response_model=dict[str, list[IPInterface]])
async def show_all_ethernet_vlans(interface: Optional[str] = None):
    """
    Returns all VLANS for a given ethernet interface.
    """

    # Screen against "all" for this operation
    if interface.lower() == "all":
        ve = ValidationError("The \"all\" meta-interface is not currently supported for this operation",400)
        return Response(content=ve.error_msg, status_code=ve.status_code)

    try:
        return await network_ethernet_service.get_vlans(interface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except VLANError as ve:
        log.error(ve)
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post("/ethernet/{interface}/vlan/{vlan}", response_model=network.config.NetworkConfigResponse)
async def create_ethernet_vlan(interface: str, vlan: Union[str,int], addresses: list[IPInterfaceAddress]):
    """
    Creates (or replaces) a VLAN on the given interface.
    """

    # Screen against "all" for this operation
    if interface.lower() == "all":
        ve = ValidationError("The \"all\" meta-interface is not currently supported for this operation", 400)
        return Response(content=ve.error_msg, status_code=ve.status_code)

    try:
        await network_ethernet_service.remove_vlan(interface=interface, vlan_id=vlan, allow_missing=True)
        await network_ethernet_service.create_vlan(interface=interface, vlan_id=vlan, addresses=addresses)
        return NetworkConfigResponse(
            result= await network_ethernet_service.get_vlans(interface)
        )

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except VLANError as ve:
        log.error(ve)
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)

@router.delete("/ethernet/{interface}/vlan/{vlan}", response_model=network.config.NetworkConfigResponse)
async def delete_ethernet_vlan(interface: str, vlan: Union[str,int], allow_missing=False):
    """
    Removes a VLAN from the given interface.
    """

    # Screen against "all" for this operation
    if interface.lower() == "all":
        ve = ValidationError("The \"all\" meta-interface is not currently supported for this operation", 400)
        return Response(content=ve.error_msg, status_code=ve.status_code)

    try:
        await network_ethernet_service.remove_vlan(interface=interface, vlan_id=vlan, allow_missing=allow_missing)
        return NetworkConfigResponse(
            result=await network_ethernet_service.get_vlans(interface)
        )

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except VLANError as ve:
        log.error(ve)
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


################################
# WLAN Management              #
################################

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
