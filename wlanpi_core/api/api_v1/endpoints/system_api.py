import asyncio
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, Response

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.api.openapi_docs import RESPONSES_MODE_CONFLICT
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import system
from wlanpi_core.services import hotspot_service, system_service

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def _read_static_device_info():
    """Cache device identity fields that only change across system reconfiguration."""
    model = system_service.get_platform()
    hostname = system_service.get_hostname()
    name = hostname.split(".")[0]
    software_ver = system_service.get_image_ver()
    return {
        "model": model,
        "hostname": hostname,
        "name": name,
        "software_version": software_ver,
    }


def _read_device_info():
    """Combine cached device identity with the current operating mode."""
    return {
        **_read_static_device_info(),
        "mode": system_service.get_mode(),
    }


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
        return await asyncio.to_thread(_read_device_info)

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
        stats = await asyncio.to_thread(system_service.get_stats)

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
    try:
        model = await asyncio.to_thread(system_service.get_model)
        return {"model": model}
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
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


@router.post(
    "/service/restart",
    response_model=system.ServiceRunning,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def restart_a_systemd_service(name: str):
    """
    Uses systemd via dbus to restart an allowed service.
    """

    try:
        return await system_service.restart_systemd_service(name)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/datetime",
    response_model=system.DateTimeInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_datetime():
    """Returns current local date/time and timezone."""
    try:
        log.debug("GET /system/datetime request")
        result = await asyncio.to_thread(system_service.get_datetime)
        log.debug("GET /system/datetime response: %s", result)
        if not result.get("datetime"):
            log.error("GET /system/datetime produced empty datetime: %s", result)
            return Response(content="Unable to determine date/time", status_code=503)
        return result
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/timezone",
    response_model=system.TimezoneInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_timezone():
    """Returns the current system timezone."""
    try:
        return await asyncio.to_thread(system_service.get_timezone)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/timezone/list",
    response_model=system.TimezoneList,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def list_timezones():
    """Returns available system timezones."""
    try:
        return await asyncio.to_thread(system_service.list_timezones)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/timezone/set",
    response_model=system.TimezoneInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def set_timezone(body: system.TimezoneSetRequest):
    """Sets the system timezone."""
    try:
        return await asyncio.to_thread(system_service.set_timezone, body.timezone)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/reg-domain/list",
    response_model=system.RegDomainList,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def list_reg_domains():
    """Returns supported WiFi regulatory domain country codes."""
    try:
        log.debug("GET /system/reg-domain/list request")
        result = system_service.list_reg_domains()
        log.debug("GET /system/reg-domain/list response: %d countries", len(result["countries"]))
        return result
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/reg-domain",
    response_model=system.RegDomainInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_reg_domain():
    """Returns the current WiFi regulatory domain."""
    try:
        log.debug("GET /system/reg-domain request")
        result = await asyncio.to_thread(system_service.get_reg_domain)
        log.debug("GET /system/reg-domain response: %s", result)
        if result.get("country") == "unknown":
            log.error("GET /system/reg-domain produced unparseable country: %s", result)
            return Response(content="Unable to determine regulatory domain", status_code=503)
        return result
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/reg-domain/set",
    response_model=system.RegDomainInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def set_reg_domain(body: system.RegDomainSetRequest):
    """Sets the WiFi regulatory domain country code."""
    try:
        log.debug("POST /system/reg-domain/set request country=%s", body.country)
        result = await asyncio.to_thread(system_service.set_reg_domain, body.country)
        log.debug("POST /system/reg-domain/set response: %s", result)
        return result
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/battery",
    response_model=system.BatteryInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_battery():
    """Returns battery status if a power supply is present."""
    try:
        return await asyncio.to_thread(system_service.get_battery)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/timezone/auto",
    response_model=system.NtpAutoInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def enable_timezone_auto():
    """Enable NTP automatic time synchronization."""
    try:
        return await asyncio.to_thread(system_service.enable_timezone_auto)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to enable NTP", status_code=503)


@router.post(
    "/reboot",
    response_model=system.PowerActionResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def reboot_device():
    """Reboot the device immediately."""
    try:
        return await asyncio.to_thread(system_service.reboot_system)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to reboot", status_code=503)


@router.post(
    "/shutdown",
    response_model=system.PowerActionResponse,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def shutdown_device():
    """Shut down the device immediately."""
    try:
        return await asyncio.to_thread(system_service.shutdown_system)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to shut down", status_code=503)


@router.get(
    "/hotspot/clients",
    response_model=system.HotspotClients,
    summary="Hotspot connected client count",
    responses={**RESPONSES_MODE_CONFLICT},
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_hotspot_clients(iface: Optional[str] = None):
    """
    Connected client count for hotspot mode.

    Returns 409 when the device is not in hotspot mode.
    """
    try:
        return await asyncio.to_thread(
            hotspot_service.get_hotspot_clients,
            iface=iface,
        )
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read hotspot clients", status_code=503)


@router.get(
    "/hotspot/ssid-passphrase",
    response_model=system.HotspotCredentials,
    summary="Hotspot SSID and WPA passphrase",
    responses={**RESPONSES_MODE_CONFLICT},
    dependencies=[Depends(verify_auth_wrapper)],
)
async def show_hotspot_ssid_passphrase():
    """
    Hotspot SSID and WPA passphrase from hostapd configuration.

    Returns 409 when the device is not in hotspot mode.
    """
    try:
        return await asyncio.to_thread(hotspot_service.get_hotspot_ssid_passphrase)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex)
        return Response(content="Unable to read hotspot credentials", status_code=503)
