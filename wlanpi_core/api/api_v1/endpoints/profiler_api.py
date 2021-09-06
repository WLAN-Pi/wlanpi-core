import logging

from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import profiler
from wlanpi_core.services import profiler_service

router = APIRouter()

log = logging.getLogger("uvicorn")


@router.get("/{mac}", response_model=profiler.Profile)
async def show_profile(mac: str):
    """
    Retrieves profile for a particular MAC
    """
    try:
        resp = await profiler_service.get_profile(mac)
        return resp
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/", response_model=profiler.Profiles)
async def read_profiles():
    """
    Retrieves all profiles on host
    """
    try:
        resp = await profiler_service.get_profiles()
        return {"profiles": resp}
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)
