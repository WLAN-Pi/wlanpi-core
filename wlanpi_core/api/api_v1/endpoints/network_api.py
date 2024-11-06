import logging
from typing import Optional, Union

from fastapi import APIRouter, Response

from wlanpi_core.constants import API_DEFAULT_TIMEOUT
from wlanpi_core.models.network.vlan.vlan_errors import VLANError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.schemas.network.config import NetworkConfigResponse
from wlanpi_core.schemas.network.network import (
    IPInterface,
    IPInterfaceAddress,
    SupplicantNetwork,
)
from wlanpi_core.services import network_ethernet_service, network_service

router = APIRouter()

log = logging.getLogger("uvicorn")


################################
# General Network Management   #
################################
@router.get("/interfaces", response_model=dict[str, list[IPInterface]])
@router.get("/interfaces/{interface}", response_model=dict[str, list[IPInterface]])
async def show_all_interfaces(interface: Optional[str] = None):
    """
    Returns all network interfaces.
    """
    if interface and interface.lower() == "all":
        interface = None

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
# Ethernet Management          #
################################
@router.get("/ethernet/{interface}", response_model=dict[str, list[IPInterface]])
async def show_all_ethernet_interfaces(interface: Optional[str] = None):
    """
    Returns all ethernet interfaces.
    """
    if interface and interface.lower() == "all":
        interface = None

    try:

        def filterfunc(i):
            iface_obj = i.model_dump()
            # TODO: Naive approach, come up with a better one later, maybe IP command has a better way to filter?
            return (
                "linkinfo" not in iface_obj
                and iface_obj["link_type"] != "loopback"
                and iface_obj["ifname"].startswith("eth")
            )

        return await network_ethernet_service.get_interfaces(
            interface=interface, custom_filter=filterfunc
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
# VLAN Management              #
################################


@router.get("/ethernet/all/vlan", response_model=dict[str, list[IPInterface]])
@router.get("/ethernet/all/vlan/{vlan}", response_model=dict[str, list[IPInterface]])
@router.get("/ethernet/{interface}/vlan", response_model=dict[str, list[IPInterface]])
@router.get(
    "/ethernet/{interface}/vlan/{vlan}", response_model=dict[str, list[IPInterface]]
)
async def show_all_ethernet_vlans(
    interface: Optional[str] = None, vlan: Optional[str] = None
):
    """
    Returns all VLANS for a given ethernet interface.
    """
    custom_filter = lambda i: True
    if not interface or interface.lower() == "all":
        interface = None
    if vlan and vlan.lower() == "all":
        vlan = None
    if vlan and vlan.lower() != "all":

        def filterfunc(i):
            return i.model_dump().get("linkinfo", {}).get(
                "info_kind"
            ) == "vlan" and i.model_dump().get("linkinfo", {}).get("info_data", {}).get(
                "id"
            ) == int(
                vlan
            )

        custom_filter = filterfunc
    try:
        return await network_ethernet_service.get_vlans(
            interface=interface, custom_filter=custom_filter
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except VLANError as ve:
        log.error(ve)
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/ethernet/{interface}/vlan/{vlan}",
    response_model=network.config.NetworkConfigResponse,
)
async def create_ethernet_vlan(
    interface: str, vlan: Union[str, int], addresses: list[IPInterfaceAddress]
):
    """
    Creates (or replaces) a VLAN on the given interface.
    """

    # Screen against "all" for this operation
    if interface and interface.lower() == "all":
        ve = ValidationError(
            'The "all" meta-interface is not currently supported for this operation',
            400,
        )
        return Response(content=ve.error_msg, status_code=ve.status_code)

    try:
        await network_ethernet_service.remove_vlan(
            interface=interface, vlan_id=vlan, allow_missing=True
        )
        await network_ethernet_service.create_vlan(
            interface=interface, vlan_id=vlan, addresses=addresses
        )
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


@router.delete(
    "/ethernet/{interface}/vlan/{vlan}",
    response_model=network.config.NetworkConfigResponse,
)
async def delete_ethernet_vlan(
    interface: str, vlan: Union[str, int], allow_missing=False
):
    """
    Removes a VLAN from the given interface.
    """

    # Screen against "all" for this operation
    if interface and interface.lower() == "all":
        ve = ValidationError(
            'The "all" meta-interface is not currently supported for this operation',
            400,
        )
        return Response(content=ve.error_msg, status_code=ve.status_code)

    try:
        await network_ethernet_service.remove_vlan(
            interface=interface, vlan_id=vlan, allow_missing=allow_missing
        )
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


@router.get("/wlan/interfaces", response_model=network.Interfaces)
async def get_wireless_interfaces(timeout: int = API_DEFAULT_TIMEOUT):
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
    "/wlan/{interface}/scan",
    response_model=network.ScanResults,
    response_model_exclude_none=True,
)
async def do_wireless_network_scan(
    scan_type: str, interface: str, timeout: int = API_DEFAULT_TIMEOUT
):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """

    try:
        return await network_service.get_wireless_network_scan_async(
            scan_type, interface, timeout
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post("/wlan/{interface}/add_network", response_model=network.NetworkSetupStatus)
async def add_wireless_network(
    interface: str,
    setup: network.WlanInterfaceSetup,
    timeout: int = API_DEFAULT_TIMEOUT,
):
    """
    Queries systemd via dbus to set a single network.
    """

    try:
        return await network_service.add_wireless_network(
            interface, setup.netConfig, setup.removeAllFirst, timeout
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/wlan/{interface}/connected",
    response_model=network.ConnectedNetwork,
    response_model_exclude_none=True,
)
async def get_current_wireless_network_details(
    interface: str, timeout: int = API_DEFAULT_TIMEOUT
):
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.get_current_wireless_network_details(
            interface, timeout
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/wlan/{interface}/disconnect",
    response_model=None,
    response_model_exclude_none=True,
)
async def disconnect_wireless_network(
    interface: str, timeout: int = API_DEFAULT_TIMEOUT
):
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.disconnect_wireless_network(interface, timeout)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/wlan/{interface}/networks",
    response_model=dict[int, SupplicantNetwork],
    response_model_exclude_none=True,
)
async def get_all_wireless_networks(interface: str, timeout: int = API_DEFAULT_TIMEOUT):
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.networks(interface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/wlan/{interface}/networks/current",
    response_model=Optional[SupplicantNetwork],
    response_model_exclude_none=True,
)
async def get_current_network(interface: str, timeout: int = API_DEFAULT_TIMEOUT):
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.current_network(interface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/wlan/{interface}/networks/{network_id}",
    response_model=SupplicantNetwork,
    response_model_exclude_none=True,
)
async def get_wireless_network(interface: str, network_id: int):
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.get_network(interface, network_id)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.delete(
    "/wlan/{interface}/networks/all",
    response_model=None,
    response_model_exclude_none=True,
)
async def remove_all_wireless_networks(interface: str):
    """
    Removes all networks on an interface
    """

    try:
        return await network_service.remove_all_networks(interface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.delete(
    "/wlan/{interface}/networks/{network_id}",
    response_model=None,
    response_model_exclude_none=True,
)
async def disconnect_wireless_network(interface: str, network_id: int):
    """
    Queries systemd via dbus to get the details of the currently connected network.
    """

    try:
        return await network_service.remove_network(
            interface,
            network_id,
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/wlan/{interface}/phy",
    response_model=Optional[dict[str, dict[str, any]]],
    response_model_exclude_none=True,
)
@router.get(
    "/wlan/phys",
    response_model=Optional[dict[str, dict[str, any]]],
    response_model_exclude_none=True,
)
async def get_interface_details(interface: Optional[str] = None):
    """
    Gets interface details via iw.
    """
    try:
        return await network_service.interface_details(interface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
