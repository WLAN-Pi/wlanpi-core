from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import system
from wlanpi_core.services import system_service

router = APIRouter()


@router.get("/service/status", response_model=system.ServiceStatus)
async def show_a_systemd_service_status(name: str):
    """
    Queries systemd via dbus to get the current status of an allowed service.
    """

    try:
        return await system_service.get_systemd_service_status(name)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/service/start", response_model=system.ServiceRunning)
async def start_a_systemd_service(name: str):
    """
    Uses systemd via dbus to start an allowed service.
    """

    try:
        return await system_service.start_systemd_service(name)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/service/stop", response_model=system.ServiceRunning)
async def stop_a_systemd_service(name: str):
    """
    Uses systemd via dbus to stop an allowed service.
    """

    try:
        return await system_service.stop_systemd_service(name)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)
