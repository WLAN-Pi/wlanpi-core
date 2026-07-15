import asyncio
import json
import os
import socket
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from dbus import Interface, SystemBus
from dbus.exceptions import DBusException

from wlanpi_core.constants import MODE_FILE, REG_DOMAIN_FILE, TIME_ZONE_FILE, WLANPI_IMAGE_FILE
from wlanpi_core.data.reg_domain_countries import (
    is_supported_reg_domain,
    reg_domain_country_entries,
)
from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.utils.general import run_command

log = get_logger(__name__)

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
    "wlanpi-grafana-scanner-wlan0",
    "wlanpi-grafana-scanner-wlan1",
    "wlanpi-grafana-scanner-wlan2",
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
_POWER_ACTION_TIMEOUT_SEC = 10


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
    model_cmd = ["wlanpi-model", "-b"]
    try:
        platform = run_command(model_cmd).stdout.strip()

    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        if isinstance(exc, RunCommandError):
            log.warning(
                "Issue getting WLAN Pi model (%s): %s", exc.return_code, exc.error_msg
            )
        else:
            log.debug("wlanpi-model unavailable (%r); returning Unknown", exc)
        return PLATFORM_UNKNOWN

    if platform.endswith("?"):
        platform = PLATFORM_UNKNOWN

    return platform


def get_model():
    """
    Method to determine which model the device is
    Uses output of "wlanpi-model -b"

    Possible strings seen in the wild:

        Pro:    Raspberry Pi Compute Module 4
        RPi3b+: Raspberry Pi 3 Model B Plus Rev 1.3
        RPi4:   Raspberry Pi 4 Model B Rev 1.1

    Errors sent to stdout, but will not exit on error
    """

    platform = PLATFORM_UNKNOWN

    # get output of wlanpi-model
    model_cmd = ["wlanpi-model", "-b"]
    try:
        platform = run_command(model_cmd).stdout.strip()

    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        if isinstance(exc, RunCommandError):
            log.warning(
                "Issue getting WLAN Pi model (%s): %s", exc.return_code, exc.error_msg
            )
        else:
            log.debug("wlanpi-model unavailable (%r); returning Unknown", exc)
        return PLATFORM_UNKNOWN

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
        CPU_JSON = run_command(cmd).grep_stdout_for_string("idle")
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
    """Check if service is in allowed services list"""
    service_name = service.replace(".service", "")
    is_allowed = service_name in allowed_services

    log.debug(
        "Checking service permissions",
        extra={
            "action": "check_service_permission",
            "service": service_name,
            "allowed": is_allowed,
        },
    )

    return is_allowed


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
        status = await asyncio.to_thread(check_service_status, name)
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
        status = await asyncio.to_thread(stop_service, name)
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
        status = await asyncio.to_thread(start_service, name)
        return {"name": name, "active": status}

    raise ValidationError(
        f"starting {name} is restricted or does not exist", status_code=400
    )


def restart_service(service: str):
    try:
        if ".service" not in service:
            service = service + ".service"
        manager.RestartUnit(service, "replace")
    except DBusException as de:
        if de._dbus_error_name == "org.freedesktop.systemd1.NoSuchUnit":
            raise ValidationError(
                f"no such unit for {service} on host", status_code=400
            )
        if de._dbus_error_name == "org.freedesktop.DBus.Error.InvalidArgs":
            raise ValidationError("Problem with the args", status_code=400)
        if (
            de._dbus_error_name
            == "org.freedesktop.DBus.Error.InteractiveAuthorizationRequired"
        ):
            raise ValidationError(
                "Interactive authentication required.", status_code=401
            )
        raise
    unit_name = service.replace(".service", "")
    return check_service_status(service)


async def restart_systemd_service(name: str):
    name = name.strip().lower()
    if is_allowed_service(name):
        active = await asyncio.to_thread(restart_service, name)
        return {"name": name, "active": active}

    raise ValidationError(
        f"restarting {name} is restricted or does not exist", status_code=400
    )


def _resolve_timezone() -> str:
    """Return best-effort IANA timezone name."""
    tz_path = Path("/etc/timezone")
    if tz_path.exists():
        tz = tz_path.read_text().strip()
        if tz and "/" in tz:
            return tz

    try:
        localtime = Path("/etc/localtime")
        if localtime.exists():
            resolved = localtime.resolve()
            parts = resolved.parts
            if "zoneinfo" in parts:
                idx = parts.index("zoneinfo")
                return "/".join(parts[idx + 1 :])
    except OSError:
        pass

    try:
        tz = run_command(
            ["timedatectl", "show", "-p", "Timezone", "--value"],
            raise_on_fail=False,
        ).stdout.strip()
        if tz and "/" in tz:
            return tz
        if tz:
            log.debug("timedatectl Timezone is non-IANA (%r); prefer /etc/timezone", tz)
            return tz
    except (RunCommandError, FileNotFoundError):
        pass

    return "UTC"


def get_datetime():
    """
    Return local date/time as ISO 8601 for API clients.

    Uses `date -Iseconds` as the canonical source because systemd's
    `timedatectl show -p LocalTime` is empty on some images (TimeUSec is used instead).
    """
    log.debug("get_datetime: resolving local time")
    try:
        local_iso = run_command(["date", "-Iseconds"], raise_on_fail=True).stdout.strip()
        display = run_command(["date"], raise_on_fail=False).stdout.strip() or None
        timezone = _resolve_timezone()
        result = {
            "datetime": local_iso,
            "timezone": timezone,
            "display": display,
            "source": "date",
        }
        log.debug(
            "get_datetime: date -Iseconds=%r timezone=%r display=%r",
            local_iso,
            timezone,
            display,
        )
        return result
    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.debug("get_datetime: date command failed (%r); using Python fallback", exc)

    timezone = _resolve_timezone()
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        timezone = "UTC"
        now = datetime.now(ZoneInfo("UTC"))
    result = {
        "datetime": now.isoformat(),
        "timezone": timezone,
        "display": now.strftime("%a %Y-%m-%d %H:%M:%S %Z"),
        "source": "fallback",
    }
    log.debug(
        "get_datetime: fallback datetime=%r timezone=%r",
        result["datetime"],
        result["timezone"],
    )
    return result


def get_timezone():
    try:
        timezone = run_command(
            ["timedatectl", "show", "-p", "Timezone", "--value"], raise_on_fail=True
        ).stdout.strip()
        return {"timezone": timezone}
    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError):
        tz_path = Path("/etc/timezone")
        if tz_path.exists():
            return {"timezone": tz_path.read_text().strip()}
        raise ValidationError("Unable to determine timezone", status_code=503)


@lru_cache(maxsize=1)
def _timezone_names() -> tuple[str, ...]:
    """Load the static tzdata name set once per service process."""
    try:
        output = run_command(["timedatectl", "list-timezones"], raise_on_fail=True).stdout
        return tuple(line.strip() for line in output.splitlines() if line.strip())
    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError):
        raise ValidationError("Unable to list timezones", status_code=503)


def list_timezones():
    """Return a fresh response around the process-cached timezone names."""
    return {"timezones": list(_timezone_names())}


def set_timezone(timezone: str):
    timezone = timezone.strip()
    if not timezone:
        raise ValidationError("timezone is required", status_code=400)
    if Path(TIME_ZONE_FILE).exists():
        run_command([TIME_ZONE_FILE, "set", timezone], raise_on_fail=True)
    else:
        run_command(["timedatectl", "set-timezone", timezone], raise_on_fail=True)
    return get_timezone()


def get_reg_domain():
    """
    Return current WiFi regulatory domain country code.

    Uses `wlanpi-reg-domain get` (not `show` — the script subcommand is `get`).
    Falls back to `iw reg get` when the script output is not a valid country code.
    """
    log.debug("get_reg_domain: reading regulatory domain")
    raw: Optional[str] = None
    source = "unknown"

    if Path(REG_DOMAIN_FILE).exists():
        result = run_command([REG_DOMAIN_FILE, "get"], raise_on_fail=False)
        candidate = (result.stdout or "").strip()
        log.debug(
            "get_reg_domain: wlanpi-reg-domain get stdout=%r stderr=%r rc=%s",
            candidate,
            (result.stderr or "").strip(),
            result.return_code,
        )
        if _is_reg_domain_tool_output(candidate):
            raw = candidate
            source = "wlanpi-reg-domain"

    if raw is None:
        crda_path = Path("/etc/default/crda")
        if crda_path.exists():
            for line in crda_path.read_text().splitlines():
                if line.strip().startswith("REGDOMAIN="):
                    candidate = line.split("=", 1)[1].strip()
                    log.debug("get_reg_domain: /etc/default/crda REGDOMAIN=%r", candidate)
                    if _is_plain_country_code(candidate):
                        raw = candidate
                        source = "crda"
                        break

    if raw is None:
        try:
            iw_raw = run_command(["iw", "reg", "get"], raise_on_fail=True).stdout.strip()
            log.debug("get_reg_domain: iw reg get stdout=%r", iw_raw)
            raw = iw_raw
            source = "iw"
        except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError) as exc:
            log.error("get_reg_domain: unable to read reg domain: %r", exc)
            raise ValidationError(
                f"Unable to read regulatory domain: {exc}", status_code=503
            )

    country = _parse_reg_country(raw)
    result = {"country": country, "raw": raw, "source": source}
    log.debug("get_reg_domain: parsed country=%r source=%r", country, source)
    if country == "unknown":
        log.warning("get_reg_domain: could not parse country from raw=%r", raw)
    return result


def set_reg_domain(country: str):
    country = country.strip().upper()
    if len(country) != 2 or not country.isalpha():
        raise ValidationError("country must be a 2-letter code", status_code=400)
    if not is_supported_reg_domain(country):
        raise ValidationError(
            f"country {country} is not in the supported regulatory domain list",
            status_code=400,
        )
    if Path(REG_DOMAIN_FILE).exists():
        run_command([REG_DOMAIN_FILE, "set", country, "--no-prompt"], raise_on_fail=True)
    else:
        run_command(["iw", "reg", "set", country], raise_on_fail=True)
    return get_reg_domain()


def list_reg_domains():
    countries = reg_domain_country_entries()
    log.debug("list_reg_domains: returning %d countries", len(countries))
    return {"countries": countries}


def _is_plain_country_code(value: str) -> bool:
    code = value.strip().upper()
    return len(code) == 2 and code.isalpha()


def _is_reg_domain_tool_output(value: str) -> bool:
    if not value or value.startswith("Error:"):
        return False
    if "Usage:" in value or "wlanpi-reg-domain" in value:
        return False
    if _is_plain_country_code(value):
        return True
    return _parse_reg_country(value) != "unknown"


def _parse_reg_country(raw: str) -> str:
    if not raw:
        return "unknown"
    text = raw.strip()
    if "\n" not in text and _is_plain_country_code(text):
        return text.upper()
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("country "):
            return line.split()[1].rstrip(":")
    return "unknown"


def enable_timezone_auto():
    """Enable NTP time synchronization via timedatectl."""
    run_command(["timedatectl", "set-ntp", "true"], raise_on_fail=True)
    ntp = run_command(
        ["timedatectl", "show", "-p", "NTP", "--value"],
        raise_on_fail=True,
    ).stdout.strip()
    timezone = get_timezone()["timezone"]
    return {"ntp": ntp.lower() in ("yes", "1", "true"), "timezone": timezone}


def reboot_system():
    """Initiate an immediate system reboot."""
    run_command(
        ["/usr/bin/systemctl", "reboot", "--no-block"],
        raise_on_fail=True,
        timeout=_POWER_ACTION_TIMEOUT_SEC,
    )
    return {"status": "rebooting"}


def shutdown_system():
    """Initiate an immediate system shutdown."""
    run_command(
        ["/usr/bin/systemctl", "poweroff", "--no-block"],
        raise_on_fail=True,
        timeout=_POWER_ACTION_TIMEOUT_SEC,
    )
    return {"status": "shutting_down"}


def get_battery():
    supply_root = Path("/sys/class/power_supply")
    if not supply_root.exists():
        return {"present": False}

    for entry in sorted(supply_root.iterdir()):
        type_file = entry / "type"
        if not type_file.exists():
            continue
        if type_file.read_text().strip() != "Battery":
            continue
        capacity = None
        capacity_file = entry / "capacity"
        if capacity_file.exists():
            try:
                capacity = int(capacity_file.read_text().strip())
            except ValueError:
                capacity = None
        status = None
        status_file = entry / "status"
        if status_file.exists():
            status = status_file.read_text().strip()
        return {
            "present": True,
            "capacity_percent": capacity,
            "status": status,
            "source": entry.name,
        }
    return {"present": False}
