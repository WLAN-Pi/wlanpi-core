from fastapi import APIRouter, Response

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import utils
from wlanpi_core.services import utils_service

router = APIRouter()


@router.get("/service_status", response_model=utils.ServiceStatus)
async def show_systemd_service_status(name: str):
    """
    Queries systemd via dbus to get the current status of an allowed service.

    Services you can query status for include:

    - wlanpi-profiler
    - wlanpi-fpms
    - wlanpi-chatbot
    - iperf3
    - ufw
    - tftpd-hpa
    - hostapd
    - wpa_supplicant
    """

    try:
        return await utils_service.get_systemd_service_status(name)
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


# @router.get("/reachability")
# def get_reachability():
#    return "TBD"


# @router.get("/mist_cloud")
# def test_mist_cloud_connectivity():
#    return "TBD"

# @router.get("/usb_devices")
# def get_usb_devices():
#    return "TBD"


# @router.get("/ufw_ports")
# def get_ufw_ports():
#    return "TBD"

# @router.get("/wpa_password")
# def get_wpa_password():
#    return "TBD"

# @router.put("/wpa_password")
# def update_wpa_password():
#    return "TBD"


@router.get("/hostname", response_model=utils.Hostname)
async def show_wlanpi_hostname():
    """
    Retrieves the current hostname of the host
    """
    try:
        return await utils_service.get_wlanpi_hostname()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        return Response(content=str(ex), status_code=500)


# @router.put("/hostname")
# def set_wlanpi_hostname(name: str):
#    """
#    Need to change /etc/hostname and /etc/hosts
#    socket.sethostname(name) does not seem to work
#    """
#    return "TODO"

# @router.put("/dns_test")
# def dns_performance_test(name: str):
#    """
#    Example: https://github.com/cleanbrowsing/dnsperftest
#    """
#    return "TODO"


@router.get("/system_info", response_model=utils.SystemInfo)
async def show_system_summary():
    """
    Retrieve system summary for the host
    """

    try:
        return await utils_service.get_system_summary_async()
    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    # except Exception as ex:
    #    return Response(content=str(ex), status_code=500)
