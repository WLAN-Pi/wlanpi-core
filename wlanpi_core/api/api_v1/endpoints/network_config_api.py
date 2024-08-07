
import logging
from typing import Optional, Union

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import system
from wlanpi_core.schemas import network_config
from wlanpi_core.services import network_config_service

router = APIRouter()

log = logging.getLogger("uvicorn")

@router.get("/ethernet/vlans", response_model=list[network_config.Vlan])
async def show_all_ethernet_vlans(interface: Optional[str] = None):
    """
    Returns all VLANS configured in /etc/network/interfaces.d/vlans
    """

    try:
        return await network_config_service.get_vlans(interface)
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


@router.post("/ethernet/vlans/create", response_model=network_config.NetworkConfigResponse)
async def create_ethernet_vlan(configuration: network_config.Vlan, require_existing_interface: bool = True):
    """
    Creates a new (or updates existing) VLAN on the given interface.
    """

    try:
        return await network_config_service.create_update_vlan(configuration, require_existing_interface=require_existing_interface)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)

@router.post("/ethernet/vlans/delete", response_model=network_config.NetworkConfigResponse)
async def delete_ethernet_vlan(interface: str, vlan_tag: Union[str,int], allow_missing=False):
    """
    Removes a VLAN from the given interface.
    """

    try:
        return await network_config_service.remove_vlan(interface=interface, vlan_tag=vlan_tag, allow_missing=allow_missing)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)

