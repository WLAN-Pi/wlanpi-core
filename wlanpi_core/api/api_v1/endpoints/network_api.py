from typing import Optional, Union

from fastapi import APIRouter, Depends, Response

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.core.config import settings
from wlanpi_core.models.network.vlan.vlan_errors import VLANError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.schemas.network.config import NetworkConfigResponse
from wlanpi_core.schemas.network.network import IPInterface, IPInterfaceAddress
from wlanpi_core import network as network_primitives
from wlanpi_core.network.lookup import resolve_interface_namespace
from wlanpi_core.services import (
    network_ethernet_service,
    network_namespace_service,
    network_service,
)

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


################################
# General Network Management   #
################################
@router.get(
    "/interfaces",
    response_model=dict[str, list[IPInterface]],
    dependencies=[Depends(verify_auth_wrapper)],
)
@router.get(
    "/interfaces/{interface}",
    response_model=dict[str, list[IPInterface]],
    dependencies=[Depends(verify_auth_wrapper)],
)
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
@router.get(
    "/ethernet/{interface}",
    response_model=dict[str, list[IPInterface]],
    dependencies=[Depends(verify_auth_wrapper)],
)
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


@router.get(
    "/ethernet/all/vlan",
    response_model=dict[str, list[IPInterface]],
    dependencies=[Depends(verify_auth_wrapper)],
)
@router.get(
    "/ethernet/all/vlan/{vlan}",
    response_model=dict[str, list[IPInterface]],
    dependencies=[Depends(verify_auth_wrapper)],
)
@router.get(
    "/ethernet/{interface}/vlan",
    response_model=dict[str, list[IPInterface]],
    dependencies=[Depends(verify_auth_wrapper)],
)
@router.get(
    "/ethernet/{interface}/vlan/{vlan}",
    response_model=dict[str, list[IPInterface]],
    dependencies=[Depends(verify_auth_wrapper)],
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
    dependencies=[Depends(verify_auth_wrapper)],
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
    dependencies=[Depends(verify_auth_wrapper)],
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


        return Response(content="Internal Server Error", status_code=500)


################################
# Network primitives (P0)      #
################################


@router.get(
    "/routing",
    response_model=network.RoutingTable,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_routing_table(namespace: Optional[str] = None):
    """Structured routing table from ``ip -j route show`` (root by default)."""
    try:
        return network_primitives.get_routing_table(namespace=namespace)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read routing table", status_code=503)


@router.get(
    "/connections/tcp",
    response_model=network.ConnectionsResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_tcp_connections(namespace: Optional[str] = None):
    """Active TCP sockets from ``ss``."""
    try:
        return network_primitives.get_tcp_connections(namespace=namespace)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to list TCP connections", status_code=503)


@router.get(
    "/connections/udp",
    response_model=network.ConnectionsResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_udp_connections(namespace: Optional[str] = None):
    """Active UDP sockets from ``ss``."""
    try:
        return network_primitives.get_udp_connections(namespace=namespace)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to list UDP connections", status_code=503)


@router.get(
    "/dhcp/leases",
    response_model=network.DhcpLeasesResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_dhcp_leases():
    """Parse dhclient lease files under ``/var/lib/dhcp``."""
    try:
        return network_primitives.get_dhcp_leases()
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read DHCP leases", status_code=503)


@router.get(
    "/interfaces/{iface}/link-stats",
    response_model=network.LinkStats,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_interface_link_stats(iface: str):
    """Per-interface link statistics via ethtool."""
    try:
        namespace = resolve_interface_namespace(iface)
        return network_primitives.get_link_stats(iface, namespace=namespace)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read link statistics", status_code=503)


@router.post(
    "/interfaces/{iface}/renew",
    response_model=network.DhcpRenewResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def renew_interface_dhcp(iface: str):
    """Renew DHCP lease for an interface in its current namespace."""
    try:
        return network_primitives.renew_interface_dhcp(iface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to renew DHCP lease", status_code=503)


@router.get(
    "/wlan/usb-drivers",
    response_model=network.WlanUsbDriversResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_wlan_usb_drivers():
    """USB-attached WLAN adapters and bound drivers."""
    try:
        return network_primitives.get_usb_wlan_drivers()
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to list USB WLAN drivers", status_code=503)


@router.get(
    "/wlan/pci-drivers",
    response_model=network.WlanPciDriversResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_wlan_pci_drivers():
    """PCI wireless devices and bound WLAN interface drivers."""
    try:
        return network_primitives.get_pci_wlan_drivers()
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to list PCI WLAN drivers", status_code=503)


################################
# WLAN Management (legacy DBus)#
################################


@router.get(
    "/wlan/getInterfaces",
    response_model=network.Interfaces,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_a_systemd_network_interfaces(timeout: int = settings.API_DEFAULT_TIMEOUT):
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
    "/wlan/scan",
    response_model=network.ScanResults,
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_a_systemd_network_scan(
    type: str, interface: str, timeout: int = settings.API_DEFAULT_TIMEOUT
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


@router.post(
    "/wlan/set-dbus",
    response_model=network.NetworkSetupStatus,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def set_a_systemd_network_dbus(
    setup: network.WlanInterfaceSetup, timeout: int = settings.API_DEFAULT_TIMEOUT
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


@router.post(
    "/wlan/set",
    response_model=network.NetworkSetupStatus,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def set_a_systemd_network(
    setup: network.WlanInterfaceSetup, timeout: int = settings.API_DEFAULT_TIMEOUT
):
    """
    Queries systemd via dbus to set a single network.
    """

    try:
        namespace_service = network_namespace_service.NetworkNamespaceService()
        namespace_service.restore_phy_to_userspace("testns")
        status = namespace_service.activate_config(
            setup.interface, setup.netConfig, "testns", setup.removeAllFirst
        )
        return status
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/wlan/revert",
    response_model=network.RevertNamespace,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def revert_wlan_namespace(
    req: network.WlanRevertRequest, timeout: int = settings.API_DEFAULT_TIMEOUT
):
    """
    Reverts the PHY and interface back to the root namespace.
    """
    try:
        namespace_service = network_namespace_service.NetworkNamespaceService()
        namespace_service.revert_to_root(
            iface=req.iface,
            namespace=req.namespace,
            delete_namespace=req.delete_namespace,
        )
        return {
            "success": True,
            "message": f"{req.iface} and phy0 reverted to root from {req.namespace}",
        }

    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/wlan/getConnected",
    response_model=network.ConnectedNetwork,
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_a_systemd_currentNetwork_details(
    interface: str, timeout: int = settings.API_DEFAULT_TIMEOUT
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
