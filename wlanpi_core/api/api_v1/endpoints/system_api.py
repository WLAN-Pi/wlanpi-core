from fastapi import APIRouter, Response
from starlette.responses import JSONResponse

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


# @router.get("/usb_devices")
# def get_usb_devices():
#    return "TBD"


# @router.get("/ufw_ports")
# def get_ufw_ports():
#    return "TBD"


@router.get("/hostname", response_model=system.Hostname)
async def show_wlanpi_hostname():
    """
    Retrieves the current hostname of the host
    """
    try:
        return await system_service.get_wlanpi_hostname()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.put("/hostname")
def set_wlanpi_hostname(name: str):
    """
    Set the hostname of the host
    """
    try:
        return Response(content="put('/hostname') not implemented yet", status_code=501)
        # return await system_service.set_wlanpi_hostname()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


@router.get("/mode")
def get_mode():
    """
    Return the current mode of the host such as classic or server.
    """
    # TODO detect "mode" we are in and return. e.g. classic, server, etc
    # TODO abstract this out to a service
    return JSONResponse(content={"mode": None}, status_code=501)


def get_uptime():
    with open("/proc/uptime", "r") as f:
        return float(f.readline().split()[0])


@router.get("/uptime")
async def show_wlanpi_uptime():
    """
    # TODO: handle errors

    Return the uptime of the host in seconds
    """
    return JSONResponse(content={"uptime": get_uptime()}, status_code=200)


@router.get("/", response_model=system.SystemInfo)
async def show_system_summary():
    """
    Retrieve system summary for the host
    """

    try:
        return await system_service.get_system_summary_async()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    # except Exception as ex:
    #    return Response(content=str(ex), status_code=500)
