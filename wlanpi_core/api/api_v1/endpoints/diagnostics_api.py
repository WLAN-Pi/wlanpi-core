from typing import Optional

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import diagnostics
from wlanpi_core.services import diagnostics_service

router = APIRouter()

"""
Ask for diagnostics is around capture/scan sensor function of the WLAN Pi.

For example, assuming the user can reach the WLAN Pi-

- Is the adapter plugged in? 
- What USB port?
- Does the adapter support monitor mode? 
- Is the wifiexplorer-sensor running? 
- Is tcpdump installed?
- Does it need sudo to run?

For diagnostics endpoints include a HTTP status code, if problem, return "false", and "error" with message.

2xx: good
4xx: bad - client’s fault (like providing a name for an non-existing interface)
5xx: bad - server’s fault (like not having tcpdump properly installed)

Example:
{“success”: true, “response”: [{“name”: “wlan0"}, {“name”: “wlan1"}]}, { “success”: false, “error”: { “code”: 1001, “message”: “interface not found”}
"""


@router.get("/", response_model=diagnostics.Diagnostics)
async def show_diagnostics():
    """
    Return diagnostic tests for sensor
    """
    try:
        resp = await diagnostics_service.get_diagnostics()
        return JSONResponse(content=resp, status_code=200)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/interfaces", response_model=diagnostics.Interfaces)
@router.get("/interfaces/{interface}", response_model=diagnostics.Interfaces)
async def diagnostics(interface: Optional[str] = None):
    try:
        if interface:
            resp = await diagnostics_service.get_interface_diagnostics(interface)
        else:
            resp = await diagnostics_service.get_interface_diagnostics()
        return JSONResponse(content=resp, status_code=200)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)
