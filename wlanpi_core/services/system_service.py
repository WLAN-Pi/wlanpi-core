from dbus import Boolean, Interface, SystemBus
from dbus.exceptions import DBusException

from wlanpi_core.models.validation_error import ValidationError

bus = SystemBus()
systemd = bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
manager = Interface(systemd, dbus_interface="org.freedesktop.systemd1.Manager")

allowed_services = [
    "wlanpi-profiler",
    "wlanpi-fpms",
    "wlanpi-chat-bot",
    "bt-agent",
    "bt-network",
    "iperf",
    "iperf3",
    "tftpd-hpa",
    "hostapd",
    "wpa_supplicant",
    "kismet",
    "grafana",
]


def is_allowed_service(service: str):
    for allowed_service in allowed_services:
        if service.replace(".service", "") == allowed_service:
            return True
    return False


def check_service_status(service: str):
    """
    Queries systemd through dbus to see if the service is running

    You can list services from the CLI like this: systemctl list-unit-files --type=service
    """
    service_running = False
    try:
        if ".service" not in service:
            service = service + ".service"
        service_proxy = bus.get_object(
            "org.freedesktop.systemd1", object_path=manager.GetUnit(service)
        )
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
        if de.args:
            if "not loaded" in de.args[0]:
                return service_running
        if de._dbus_error_name == "org.freedesktop.systemd1.NoSuchUnit":
            raise ValidationError(
                f"no such unit for {service} on host", status_code=503
            )
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)
    return service_running


async def get_systemd_service_status(name: str):
    """
    Queries systemd via dbus to get the current status of an allowed service.
    """
    status = ""
    name = name.strip().lower()
    if is_allowed_service(name):
        status = check_service_status(name)
        return {"name": name, "active": status}

    raise ValidationError(
        f"{name} access is restricted or does not exist", status_code=400
    )


def stop_service(service: str):
    try:
        if ".service" not in service:
            service = service + ".service"
        manager.StopUnit(service, "replace")
        manager.DisableUnitFiles([service], Boolean(False))
    except DBusException as de:
        if de._dbus_error_name == "org.freedesktop.systemd1.NoSuchUnit":
            raise ValidationError(
                f"no such unit for {service} on host", status_code=400
            )
        if de._dbus_error_name == "org.freedesktop.DBus.Error.InvalidArgs":
            raise ValidationError(f"Problem with the args", status_code=400)
        if (
            de._dbus_error_name
            == "org.freedesktop.DBus.Error.InteractiveAuthorizationRequired"
        ):
            raise ValidationError(
                f"Interactive authentication required.", status_code=401
            )
    return False


async def stop_systemd_service(name: str):
    """
    Queries systemd via dbus to get the current status of an allowed service.
    """
    status = ""
    name = name.strip().lower()
    if is_allowed_service(name):
        status = stop_service(name)
        return {"name": name, "active": status}

    raise ValidationError(
        f"stopping {name} is restricted or does not exist", status_code=400
    )


def start_service(service: str):
    try:
        if ".service" not in service:
            service = service + ".service"
        manager.EnableUnitFiles([service], Boolean(False), Boolean(True))
        manager.StartUnit(service, "replace")
    except DBusException as de:
        if de._dbus_error_name == "org.freedesktop.systemd1.NoSuchUnit":
            raise ValidationError(
                f"no such unit for {service} on host", status_code=400
            )
        if de._dbus_error_name == "org.freedesktop.DBus.Error.InvalidArgs":
            raise ValidationError(f"Problem with the args", status_code=400)
        if (
            de._dbus_error_name
            == "org.freedesktop.DBus.Error.InteractiveAuthorizationRequired"
        ):
            raise ValidationError(
                f"Interactive authentication required.", status_code=401
            )
    return True


async def start_systemd_service(name: str):
    status = ""
    name = name.strip().lower()
    if is_allowed_service(name):
        status = start_service(name)
        return {"name": name, "active": status}

    raise ValidationError(
        f"starting {name} is restricted or does not exist", status_code=400
    )
