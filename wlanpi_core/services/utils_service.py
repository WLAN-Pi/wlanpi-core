import platform
from socket import gethostname

from dbus import Interface, SystemBus
from dbus.exceptions import DBusException

from wlanpi_core.models.validation_error import ValidationError


def check_service_status(service):
    """queries systemd through dbus to see if the service is running"""
    service_running = False
    bus = SystemBus()
    systemd = bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
    manager = Interface(systemd, dbus_interface="org.freedesktop.systemd1.Manager")
    try:
        service_unit = (
            service
            if service.endswith(".service")
            else manager.GetUnit(f"{service}.service")
        )
        service_proxy = bus.get_object("org.freedesktop.systemd1", str(service_unit))
        service_props = Interface(
            service_proxy, dbus_interface="org.freedesktop.DBus.Properties"
        )
        service_load_state = service_props.Get(
            "org.freedesktop.systemd1.Unit", "LoadState"
        )
        service_active_state = service_props.Get(
            "org.freedesktop.systemd1.Unit", "ActiveState"
        )
        if service_load_state == "loaded" and service_active_state == "active":
            service_running = True
    except DBusException as de:
        if de._dbus_error_name == "org.freedesktop.systemd1.NoSuchUnit":
            raise ValidationError(
                f"{service} service does not exist on host", status_code=400
            )
    return service_running


allowed_services = [
    "profiler",
    "wlanpi-profiler",
    "fpms",
    "wlanpi-fpms",
    "iperf3",
    "ufw",
    "tftpd-hpa",
    "hostapd",
    "wpa_supplicant",
]


async def get_systemd_service_status(name: str):
    """
    Queries systemd via dbus to get status of a given service.
    """
    status = ""
    name = name.strip().lower()
    if name in allowed_services:
        status = check_service_status(name)
        return {"name": name, "active": status}

    raise ValidationError(
        f"{name} access is restricted or does not exist", status_code=400
    )


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


async def get_wlanpi_hostname():
    return {"hostname": gethostname()}


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


def get_wlanpi_version():
    wlanpi_version = ""
    try:
        with open("/etc/wlanpi-release") as _file:
            lines = _file.read().splitlines()
            for line in lines:
                if "VERSION" in line:
                    wlanpi_version = "{0}".format(
                        line.split("=")[1].replace('"', "").strip()
                    )
    except OSError:
        pass
    return wlanpi_version


async def get_system_summary():
    uname = platform.uname()
    summary = {}
    summary["system"] = uname.system
    summary["build"] = get_wlanpi_version()
    summary["node_name"] = uname.node
    summary["release"] = uname.release
    summary["version"] = uname.version
    summary["machine"] = uname.machine
    summary["processor"] = uname.processor
    return summary
