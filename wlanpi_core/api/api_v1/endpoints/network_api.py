import asyncio
import json
from typing import Optional, Union

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from wlanpi_core.adapters.discovery import list_interfaces
from wlanpi_core.api.openapi_docs import RESPONSES_SCAN

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.core.config import settings
from wlanpi_core.models.network.vlan.vlan_errors import VLANError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.schemas.common.errors import (
    ApiErrorResponse,
    DeprecatedEndpointResponse,
)
from wlanpi_core.schemas.network.config import NetworkConfigResponse
from wlanpi_core.schemas.network.network import IPInterface, IPInterfaceAddress
from wlanpi_core import network as network_primitives
from wlanpi_core.network.lookup import resolve_interface_namespace
from wlanpi_core.services import (
    network_ethernet_service,
    network_namespace_service,
)
from wlanpi_core.wlan.scan import NoScanAdapterError, wlan_scan
from wlanpi_core.wpa.status import get_wpa_status

router = APIRouter()
legacy_wlan_router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


def _read_interface_link_stats(iface: str):
    """Resolve interface ownership and read link stats in one worker thread."""
    namespace = resolve_interface_namespace(iface)
    return network_primitives.get_link_stats(iface, namespace=namespace)


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
async def show_all_ethernet_interfaces(interface: str):
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
        return await asyncio.to_thread(
            network_primitives.get_routing_table,
            namespace=namespace,
        )
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
        return await asyncio.to_thread(
            network_primitives.get_tcp_connections,
            namespace=namespace,
        )
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
        return await asyncio.to_thread(
            network_primitives.get_udp_connections,
            namespace=namespace,
        )
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
        return await asyncio.to_thread(network_primitives.get_dhcp_leases)
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
        return await asyncio.to_thread(_read_interface_link_stats, iface=iface)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read link statistics", status_code=503)


@router.post(
    "/interfaces/{iface}/renew",
    response_model=network.DhcpRenewResponse,
    responses={
        400: {
            "model": ApiErrorResponse,
            "description": "Invalid interface name",
        },
        409: {
            "model": ApiErrorResponse,
            "description": "Interface is not managed by systemd-networkd",
        },
        503: {
            "model": ApiErrorResponse,
            "description": "networkctl failed or timed out",
        },
    },
    dependencies=[Depends(verify_auth_wrapper)],
)
async def renew_interface_dhcp(iface: str):
    """Renew DHCP for a systemd-networkd-managed root interface."""
    try:
        return await network_primitives.renew_interface_dhcp(iface)
    except ValidationError as ve:
        error = (
            "INTERFACE_NOT_NETWORKD_MANAGED"
            if ve.status_code == 409
            else "INVALID_INTERFACE"
        )
        return JSONResponse(
            content={"error": error, "message": ve.error_msg},
            status_code=ve.status_code,
        )
    except Exception as ex:
        log.error(ex)
        return JSONResponse(
            content={
                "error": "DHCP_RENEW_FAILED",
                "message": "Unable to renew DHCP lease",
            },
            status_code=503,
        )


@router.get(
    "/wlan/usb-drivers",
    response_model=network.WlanUsbDriversResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_wlan_usb_drivers():
    """
    USB-attached WLAN adapters and bound drivers.

    Returns HTTP 200 with ``adapters: []`` when radios are PCI/on-board only.
    Check ``interfaces_scanned`` — if > 0 and ``adapters`` is empty, use
    ``GET /network/wlan/pci-drivers`` for built-in WiFi.
    """
    try:
        return await asyncio.to_thread(network_primitives.get_usb_wlan_drivers)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to list USB WLAN drivers", status_code=503)


@router.get(
    "/wlan/pci-drivers",
    response_model=network.WlanPciDriversResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_wlan_pci_drivers():
    """
    PCI/platform wireless devices and bound WLAN interface drivers.

    ``pci_devices`` comes from lspci; ``adapters`` maps iw dev interfaces to
    drivers. Both lists can be populated independently.
    """
    try:
        return await asyncio.to_thread(network_primitives.get_pci_wlan_drivers)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to list PCI WLAN drivers", status_code=503)


################################
# WLAN Management (legacy DBus)#
################################


@legacy_wlan_router.get(
    "/wlan/getInterfaces",
    response_model=network.Interfaces,
    dependencies=[Depends(verify_auth_wrapper)],
    deprecated=True,
    summary="[Deprecated] List wireless interfaces",
)
async def get_a_systemd_network_interfaces(timeout: int = settings.API_DEFAULT_TIMEOUT):
    """
    **Deprecated** — prefer `GET /api/v1/network/config/status`.

    **Replacement:** `GET /api/v1/network/config/status`

    **Behaviour today:** delegates to `iw dev` (no DBus).
    """
    del timeout
    try:
        interfaces = list_interfaces()
        return {"interfaces": [{"interface": name} for name in interfaces]}
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@legacy_wlan_router.get(
    "/wlan/scan",
    response_model=network.ScanResults,
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
    deprecated=True,
    summary="[Deprecated] WLAN scan",
    responses={**RESPONSES_SCAN},
)
async def get_a_systemd_network_scan(
    type: str, interface: str, timeout: int = settings.API_DEFAULT_TIMEOUT
):
    """
    **Deprecated** — use `GET /api/v1/utils/wlan/scan`.

    **Replacement:** `GET /api/v1/utils/wlan/scan`

    Delegates to the namespace-aware scan primitive; maps to legacy `nets[]`.
    Query `type` is ignored. Pass `interface` as the scan iface.
    """
    del type, timeout
    try:
        result = await asyncio.to_thread(
            wlan_scan,
            iface=interface or None,
            namespace=None,
            hidden=True,
            detail="short",
        )
        if result.get("needsSelection"):
            return Response(
                content=json.dumps(
                    {
                        "error": "NEEDS_SELECTION",
                        "candidates": result.get("candidates", []),
                    }
                ),
                status_code=409,
                media_type="application/json",
            )
        nets = []
        for entry in result.get("networks", []):
            nets.append(
                network.ScanItem(
                    ssid=entry.get("ssid", ""),
                    bssid=entry.get("bssid", ""),
                    key_mgmt=entry.get("key_mgmt", "unknown"),
                    signal=entry.get("signal", 0),
                    freq=entry.get("freq", 0),
                    minrate=entry.get("minrate", 0),
                )
            )
        return network.ScanResults(nets=nets)
    except NoScanAdapterError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": "NO_SCAN_ADAPTER", "candidates": exc.candidates},
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@legacy_wlan_router.post(
    "/wlan/set-dbus",
    status_code=410,
    response_model=DeprecatedEndpointResponse,
    dependencies=[Depends(verify_auth_wrapper)],
    deprecated=True,
    summary="[Deprecated] DBus network setup — removed",
)
async def set_a_systemd_network_dbus(
    setup: network.WlanInterfaceSetup, timeout: int = settings.API_DEFAULT_TIMEOUT
):
    """
    **Deprecated — returns 410 Gone.**

    **Replacement:** `POST /api/v1/network/config/` then `POST /api/v1/network/config/activate/{id}`
    """
    del setup, timeout
    return DeprecatedEndpointResponse(
        message="Use POST /api/v1/network/config/ then POST /api/v1/network/config/activate/{id}",
        replacement="/api/v1/network/config/",
    )


@legacy_wlan_router.post(
    "/wlan/set",
    status_code=410,
    response_model=DeprecatedEndpointResponse,
    dependencies=[Depends(verify_auth_wrapper)],
    deprecated=True,
    summary="[Deprecated] Namespace stub — removed",
)
async def set_a_systemd_network(
    setup: network.WlanInterfaceSetup, timeout: int = settings.API_DEFAULT_TIMEOUT
):
    """
    **Deprecated — returns 410 Gone.**

    **Replacement:** same as `/wlan/set-dbus` — use `/network/config/` + activate.
    """
    del setup, timeout
    return DeprecatedEndpointResponse(
        message="Use POST /api/v1/network/config/ then POST /api/v1/network/config/activate/{id}",
        replacement="/api/v1/network/config/",
    )


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


@legacy_wlan_router.get(
    "/wlan/getConnected",
    response_model=network.ConnectedNetwork,
    response_model_exclude_none=True,
    dependencies=[Depends(verify_auth_wrapper)],
    deprecated=True,
    summary="[Deprecated] Connected network details",
)
async def get_a_systemd_currentNetwork_details(
    interface: str, timeout: int = settings.API_DEFAULT_TIMEOUT
):
    """
    **Deprecated** — prefer `GET /api/v1/network/config/status` plus wpa state.

    **Replacement:** `GET /api/v1/network/config/status`

    **Behaviour today:** delegates to `wpa_cli status` for the given `interface`.
    """
    del timeout
    try:
        status = await asyncio.to_thread(get_wpa_status, interface, None)
        wpa = status.get("wpa_status") or {}
        connected = wpa.get("wpa_state") == "COMPLETED"
        connected_net = None
        scan_match = status.get("connected_scan")
        if connected and scan_match:
            connected_net = network.ScanItem(
                ssid=scan_match.get("ssid", wpa.get("ssid", "")),
                bssid=scan_match.get("bssid", wpa.get("bssid", "")),
                key_mgmt=scan_match.get("key_mgmt", "unknown"),
                signal=scan_match.get("signal", 0),
                freq=scan_match.get("freq", 0),
                minrate=scan_match.get("minrate", 0),
            )
        elif connected and wpa.get("ssid"):
            connected_net = network.ScanItem(
                ssid=wpa.get("ssid", ""),
                bssid=wpa.get("bssid", ""),
                key_mgmt="unknown",
                signal=0,
                freq=0,
                minrate=0,
            )
        return network.ConnectedNetwork(
            connectedStatus=connected,
            connectedNet=connected_net,
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
