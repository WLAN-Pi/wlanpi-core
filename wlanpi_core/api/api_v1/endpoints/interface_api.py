import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.responses import Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import interface_service

router = APIRouter()


@router.get("/get_channels/{interface}")
async def show_interfaces_list(interface: str):
    """
    Return a list of channels for a given interface
    """
    try:
        resp = await interface_service.get_channels(interface)
        return JSONResponse(content=resp, status_code=200)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/get_interfaces")
async def show_interfaces_list():
    """
    Return a list of phy80211 compatible interfaces
    """
    interfaces = []
    path = "/sys/class/net"
    for net, ifaces, files in os.walk(path):
        for iface in ifaces:
            for dirpath, dirnames, filenames in os.walk(os.path.join(path, iface)):
                if "phy80211" in dirnames:
                    interfaces.append(iface)
    # TODO: exception handling
    # TODO: if list is empty, return what status code?
    return JSONResponse(interfaces, status_code=200)
