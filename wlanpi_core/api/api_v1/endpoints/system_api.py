import subprocess

from fastapi import APIRouter, Depends, Response

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import system
from wlanpi_core.services import system_service
from wlanpi_core.utils.general import run_command

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


@router.get(
    "/device/info",
    response_model=system.DeviceInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_device_info():
    """
    Returns core information about the PI.

    Commands:
     - Uses 'wlanpi-model -b' to query the device model.
     - Uses '/usr/bin/hostname' to query the device hostname.
     - Uses '/etc/wlanpi-release' to query the device software version.
     - Uses '/etc/wlanpi-state' to query the device mode.
    """

    try:
        # get output of wlanpi-model
        model = system_service.get_platform()
        hostname = system_service.get_hostname()
        name = hostname.split(".")[0]
        software_ver = system_service.get_image_ver()
        mode = system_service.get_mode()

        return {
            "model": model,
            "hostname": hostname,
            "name": name,
            "software_version": software_ver,
            "mode": mode,
        }

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/device/stats",
    response_model=system.DeviceStats,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def device_stats():
    """
    Returns system stats about the PI.

    See get_stats in system_service.py
    """

    try:
        # get system stats
        stats = system_service.get_stats()

        return stats

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/device/model",
    response_model=system.DeviceModel,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_device_model():
    """
    Uses 'wlanpi-model -b' to query the device model.
    """

    # get output of wlanpi-model
    model_cmd = "wlanpi-model -b"
    try:
        platform = run_command(model_cmd).stdout.strip()

        if platform.endswith("?"):
            platform = "Unknown"

        return {"model": platform}

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except subprocess.CalledProcessError as exc:
        log.error(exc)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/service/status",
    response_model=system.ServiceStatus,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_a_systemd_service_status(name: str):
    """
    Queries systemd via dbus to get the current status of an allowed service.
    """

    try:
        return await system_service.get_systemd_service_status(name)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/service/start",
    response_model=system.ServiceRunning,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def start_a_systemd_service(name: str):
    """
    Uses systemd via dbus to start an allowed service.
    """

    try:
        return await system_service.start_systemd_service(name)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/service/stop",
    response_model=system.ServiceRunning,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def stop_a_systemd_service(name: str):
    """
    Uses systemd via dbus to stop an allowed service.
    """

    try:
        return await system_service.stop_systemd_service(name)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)
