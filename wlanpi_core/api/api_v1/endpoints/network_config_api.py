
import logging
from typing import Optional, Union

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network_config
from wlanpi_core.schemas.network.network import IPInterfaceAddress
from wlanpi_core.schemas.network_config import NetworkConfigResponse
from wlanpi_core.services import network_config_service

router = APIRouter()

log = logging.getLogger("uvicorn")

@router.get("/ethernet/vlans", response_model=list[network_config.Vlan])
async def show_all_ethernet_vlans(interface: Optional[str] = None):
    """
    Returns all VLANS configured in /etc/network/interfaces.d/vlans
    """

    try:
        return NetworkConfigResponse(
            result=await network_config_service.get_vlans(interface)
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
#
# @router.get("/ethernet/vlan")
# async def show_an_ethernet_vlan(name: str):
#     """
#     Queries systemd via dbus to get the current status of an allowed service.
#     """
#
#     try:
#         return await network_config_service.get_vlans(name)
#     except ValidationError as ve:
#         return Response(content=ve.error_msg, status_code=ve.status_code)
#     except Exception as ex:
#         log.error(ex)
#         return Response(content="Internal Server Error", status_code=500)


@router.post("/ethernet/vlans", response_model=network_config.NetworkConfigResponse)
async def create_ethernet_vlan(interface: str, vlan_tag: Union[str,int], addresses: list[IPInterfaceAddress]):
    """
    Creates (or replaces) a VLAN on the given interface.
    """

    try:
        await network_config_service.remove_vlan(interface=interface, vlan_id=vlan_tag, allow_missing=True)
        await network_config_service.create_vlan(interface=interface, vlan_id=vlan_tag, addresses=addresses)
        return NetworkConfigResponse(
            result= await network_config_service.get_vlans(interface)
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)

@router.delete("/ethernet/vlans", response_model=network_config.NetworkConfigResponse)
async def delete_ethernet_vlan(interface: str, vlan_tag: Union[str,int], allow_missing=False):
    """
    Removes a VLAN from the given interface.
    """

    try:
        await network_config_service.remove_vlan(interface=interface, vlan_id=vlan_tag, allow_missing=allow_missing)
        return NetworkConfigResponse(
            result=await network_config_service.get_vlans(interface)
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)

