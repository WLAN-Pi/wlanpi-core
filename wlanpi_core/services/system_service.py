import json
import logging
import os
import socket
import subprocess

from dbus import Interface, SystemBus
from dbus.exceptions import DBusException

from wlanpi_core.constants import MODE_FILE, WLANPI_IMAGE_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.utils.general import run_command

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
    "grafana-server",
    "cockpit",
    "wlanpi-grafana-scanner",
    "wlanpi-grafana-health",
    "wlanpi-grafana-internet",
    "wlanpi-grafana-wispy-24",
    "wlanpi-grafana-wispy-5",
    "wlanpi-grafana-wipry-lp-24",
    "wlanpi-grafana-wipry-lp-5",
    "wlanpi-grafana-wipry-lp-6",
    "wlanpi-grafana-wipry-lp-stop",
    "wpa_supplicant",
    "wpa_supplicant@wlan0",
]

PLATFORM_UNKNOWN = "Unknown"


def get_mode():
    valid_modes = ["classic", "wconsole", "hotspot", "wiperf", "server", "bridge"]

    # check mode file exists and read mode...create with classic mode if not
    if os.path.isfile(MODE_FILE):
        with open(MODE_FILE, "r") as f:
            current_mode = f.readline().strip()

        # send msg to stdout & exit if mode invalid
        if not current_mode in valid_modes:
            print(
                "The mode read from {} is not a valid mode of operation: {}".format(
                    MODE_FILE, current_mode
                )
            )
            # sys.exit()
    else:
        # create the mode file as it does not exist
        with open(MODE_FILE, "w") as f:
            current_mode = "classic"
            f.write(current_mode)

    return current_mode


def get_image_ver():
    wlanpi_ver = "unknown"

    if os.path.isfile(WLANPI_IMAGE_FILE):
        with open(WLANPI_IMAGE_FILE, "r") as f:
            lines = f.readlines()

        # pull out the version number for the FPMS home page
        for line in lines:
            (name, value) = line.split("=")
            if name == "VERSION":
                wlanpi_ver = value.strip()
                break

    return wlanpi_ver


def get_hostname():
    try:

        hostname = run_command("/usr/bin/hostname").stdout.strip()
        if not "." in hostname:
            domain = "local"
            try:
                output = run_command("/usr/bin/hostname -d").stdout.strip()
                if len(output) != 0:
                    domain = output
            except:
                pass
            hostname = f"{hostname}.{domain}"
        return hostname
    except:
        pass

    return None


def get_platform():
    """
    Method to determine which platform we're running on.
    Uses output of "cat /proc/cpuinfo"

    Possible strings seen in the wild:

        Pro:    Raspberry Pi Compute Module 4
        RPi3b+: Raspberry Pi 3 Model B Plus Rev 1.3
        RPi4:   Raspberry Pi 4 Model B Rev 1.1

    Errors sent to stdout, but will not exit on error
    """

    platform = PLATFORM_UNKNOWN

    # get output of wlanpi-model
    model_cmd = "wlanpi-model -b"
    try:
        platform = run_command(model_cmd).stdout.strip()

    except RunCommandError as exc:
        logging.warning(f"Issue getting wlanpi model ({exc.return_code}): {exc.error_msg}")
        return "Unknown"
    except subprocess.CalledProcessError as exc:
        exc.model.decode()
        # print("Err: issue running 'wlanpi-model -b' : ", model)
        return "Unknown"

    if platform.endswith("?"):
        platform = PLATFORM_UNKNOWN

    return platform


def get_stats():
    # figure out our IP
    IP = ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(("10.255.255.255", 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = "127.0.0.1"
    finally:
        s.close()

    ipStr = f"{IP}"

    # determine CPU load
    # cmd = "top -bn1 | grep load | awk '{printf \"%.2f%%\", $(NF-2)}'"
    cmd = "mpstat 1 1 -o JSON"
    try:
        CPU_JSON = run_command(cmd).grep_stdout_for_string('idle')
        CPU_IDLE = json.loads(CPU_JSON)["idle"]
        CPU = "{0:.2f}%".format(100 - CPU_IDLE)
        if CPU_IDLE == 100:
            CPU = "0%"
        if CPU_IDLE == 0:
            CPU = "100%"
    except Exception:
        CPU = "unknown"

    # determine mem useage
    cmd = "free -m | awk 'NR==2{printf \"%s/%sMB %.2f%%\", $3,$2,$3*100/$2 }'"
    try:
        MemUsage = run_command(cmd, shell=True).stdout.strip()
    except Exception:
        MemUsage = "unknown"

    # determine disk util
    cmd = 'df -h | awk \'$NF=="/"{printf "%d/%dGB %s", $3,$2,$5}\''
    try:
        Disk = run_command(cmd, shell=True).stdout.strip()
    except Exception:
        Disk = "unknown"

    # determine temp
    try:
        tempI = int(open("/sys/class/thermal/thermal_zone0/temp").read())
    except Exception:
        tempI = "unknown"

    if tempI > 1000:
        tempI = tempI / 1000
    tempStr = "%sC" % str(round(tempI, 1))

    # determine uptime
    cmd = "uptime -p | sed -r 's/up|,//g' | sed -r 's/\s*week[s]?/w/g' | sed -r 's/\s*day[s]?/d/g' | sed -r 's/\s*hour[s]?/h/g' | sed -r 's/\s*minute[s]?/m/g'"
    try:
        uptime = run_command(cmd, shell=True).stdout.strip()
    except Exception:
        uptime = "unknown"

    uptimeStr = f"{uptime}"

    results = {
        "ip": ipStr,
        "cpu": str(CPU),
        "ram": str(MemUsage),
        "disk": str(Disk),
        "cpu_temp": tempStr,
        "uptime": uptimeStr,
    }

    return results


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
        # manager.DisableUnitFiles([service], Boolean(False))
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
        # manager.EnableUnitFiles([service], Boolean(False), Boolean(True))
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
