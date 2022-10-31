from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.responses import Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import interface
from wlanpi_core.services import interface_service

router = APIRouter()


@router.get("/wiphys", response_model=interface.Wiphys)
async def show_interfaces_list():
    """
    Return a list interfaces and associated channelization
    """
    try:
        resp = await interface_service.get_wiphys()
        return JSONResponse(content=resp, status_code=200)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)

@router.get("/wiphys/{interface}/iw_scan", response_model=interface.IwScanResults)
async def show_wiphy_scan(interface: str):
    """
    Retrieves iw scan for given interface
    """
    try:
        resp = await interface_service.get_scan_results(interface)
        return resp
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)