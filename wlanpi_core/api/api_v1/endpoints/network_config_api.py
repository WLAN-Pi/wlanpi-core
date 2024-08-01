import logging

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import system
from wlanpi_core.schemas import network_config
from wlanpi_core.services import network_config_service

router = APIRouter()

log = logging.getLogger("uvicorn")

@router.get("/ethernet/vlans", response_model=list[network_config.Vlan])
async def show_all_ethernet_vlans(interface: str = 'eth0'):
    """
    Queries systemd via dbus to get the current status of an allowed service.
    """

    try:
        return await network_config_service.get_vlans()
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