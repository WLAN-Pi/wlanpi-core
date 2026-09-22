"""System service layer querying device and systemd state."""

import asyncio
import json
import os
import socket
import subprocess
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psutil
from dbus import Interface, SystemBus
from dbus.exceptions import DBusException

from wlanpi_core.constants import (
    MODE_FILE,
    REG_DOMAIN_FILE,
    TIME_ZONE_FILE,
    WLANPI_IMAGE_FILE,
)
from wlanpi_core.core.logging import get_logger
from wlanpi_core.data.reg_domain_countries import (
    is_supported_reg_domain,
    reg_domain_country_entries,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.utils.general import run_command

log = get_logger(__name__)

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
_SYSTEMD_DBUS_TIMEOUT_SEC = 10
_SYSTEMD_BUS_NAME = "org.freedesktop.systemd1"
_SYSTEMD_OBJECT_PATH = "/org/freedesktop/systemd1"
_SYSTEMD_MANAGER_INTERFACE = "org.freedesktop.systemd1.Manager"
_SYSTEMD_PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
_SYSTEMD_CONNECTION_ERRORS = {
    "org.freedesktop.DBus.Error.Disconnected",
    "org.freedesktop.DBus.Error.FileNotFound",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
    "org.freedesktop.DBus.Error.NoReply",
    "org.freedesktop.DBus.Error.NoServer",
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.Timeout",
    "org.freedesktop.DBus.Error.TimedOut",
}

_systemd_client: tuple[object, object] | None = None
_systemd_lock = threading.RLock()


def _reset_systemd_client() -> None:
    """Discard cached D-Bus proxies so the next request reconnects."""
    global _systemd_client
    with _systemd_lock:
        _systemd_client = None


def _get_systemd_client() -> tuple[Any, Any]:
    """Create the systemd D-Bus proxies lazily, never during app import."""
    global _systemd_client
    with _systemd_lock:
        if _systemd_client is not None:
            return _systemd_client

        try:
            bus = SystemBus()
            systemd = bus.get_object(_SYSTEMD_BUS_NAME, _SYSTEMD_OBJECT_PATH)
            manager = Interface(
                systemd,
                dbus_interface=_SYSTEMD_MANAGER_INTERFACE,
            )
        except (DBusException, OSError) as exc:
            log.error("Unable to connect to system D-Bus: %r", exc)
            raise ValidationError(
                "System D-Bus is unavailable",
                status_code=503,
            ) from exc

        _systemd_client = (bus, manager)
        return _systemd_client


def _dbus_error_name(exc: DBusException) -> str | None:
    """Read a D-Bus error name without relying on private exception fields."""
    try:
        return exc.get_dbus_name()
    except Exception:
        return None


def _raise_systemd_dbus_error(
    exc: DBusException,
    *,
    action: str,
    service: str,
    missing_status: int = 400,
) -> None:
    """Translate systemd D-Bus errors into stable API-facing failures."""
    error_name = _dbus_error_name(exc)
    if error_name == "org.freedesktop.systemd1.NoSuchUnit":
        raise ValidationError(
            f"no such unit for {service} on host",
            status_code=missing_status,
        ) from exc
    if error_name == "org.freedesktop.DBus.Error.InvalidArgs":
        raise ValidationError("Problem with the args", status_code=400) from exc
    if error_name == "org.freedesktop.DBus.Error.InteractiveAuthorizationRequired":
        raise ValidationError(
            "Interactive authentication required.",
            status_code=401,
        ) from exc

    if error_name in _SYSTEMD_CONNECTION_ERRORS:
        _reset_systemd_client()

    log.error(
        "System D-Bus failed while %s %s (%s): %r",
        action,
        service,
        error_name or "unknown error",
        exc,
    )
    raise ValidationError(
        f"Unable to {action} {service} through system D-Bus",
        status_code=503,
    ) from exc


def get_mode() -> str:
    """Return the current device mode."""
    valid_modes = ["classic", "wconsole", "hotspot", "wiperf", "server", "bridge"]

    try:
        with open(MODE_FILE, encoding="utf-8") as mode_file:
            current_mode = mode_file.readline().strip()
    except FileNotFoundError:
        # Missing state means the device has not selected a non-default mode. A
        # read-only API guard must not create or mutate system state.
        return "classic"
    except OSError as exc:
        log.warning("Unable to read device mode from %s: %s", MODE_FILE, exc)
        raise ValidationError("Unable to read device mode", status_code=503) from exc

    if current_mode not in valid_modes:
        log.warning(
            "Invalid device mode %r read from %s",
            current_mode,
            MODE_FILE,
        )

    return current_mode


def get_image_ver() -> str:
    """Return the software version from the WLAN Pi image file."""
    wlanpi_ver = "unknown"

    if os.path.isfile(WLANPI_IMAGE_FILE):
        with open(WLANPI_IMAGE_FILE, encoding="utf-8") as image_file:
            lines = image_file.readlines()

        # pull out the version number for the FPMS home page
        for line in lines:
            name, separator, value = line.partition("=")
            if not separator:
                continue
            if name == "VERSION":
                wlanpi_ver = value.strip()
                break

    return wlanpi_ver


def get_hostname() -> str:
    """Return the fully qualified hostname."""
    try:
        hostname = run_command(["/usr/bin/hostname"]).stdout.strip()
    except (RunCommandError, OSError) as exc:
        log.warning("Unable to read hostname with /usr/bin/hostname: %s", exc)
        hostname = socket.gethostname().strip()

    if not hostname:
        raise ValidationError("Unable to determine hostname", status_code=503)

    if "." not in hostname:
        domain = "local"
        try:
            output = run_command(["/usr/bin/hostname", "-d"]).stdout.strip()
            if output:
                domain = output
        except (RunCommandError, OSError) as exc:
            log.debug("Unable to read hostname domain: %s", exc)
        hostname = f"{hostname}.{domain}"
    return hostname


def get_platform() -> str:
    """
    Determine which platform we're running on.

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

    except (
        RunCommandError,
        subprocess.CalledProcessError,
        FileNotFoundError,
        OSError,
    ) as exc:
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


def get_model() -> str:
    """
    Determine which model the device is.

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

    except (
        RunCommandError,
        subprocess.CalledProcessError,
        FileNotFoundError,
        OSError,
    ) as exc:
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


def _read_cpu_temperature() -> str:
    """Return the thermal-zone temperature without mixing strings and numbers."""
    try:
        raw_temperature = Path("/sys/class/thermal/thermal_zone0/temp").read_text(
            encoding="utf-8"
        )
        temperature: float = int(raw_temperature.strip())
    except (OSError, ValueError):
        return "unknown"

    if temperature > 1000:
        temperature = temperature / 1000
    return f"{round(temperature, 1)}C"


def get_stats() -> dict[str, str]:
    """Return device stats such as CPU, RAM, disk, and uptime."""
    # figure out our IP
    IP = ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(("10.255.255.255", 1))
        IP = s.getsockname()[0]
    except OSError:
        IP = "127.0.0.1"
    finally:
        s.close()

    ipStr = f"{IP}"

    # determine CPU load
    cmd = "mpstat 1 1 -o JSON"
    try:
        CPU_JSON = run_command(cmd).grep_stdout_for_string("idle")
        if isinstance(CPU_JSON, list):
            CPU_JSON = "\n".join(CPU_JSON)
        CPU_IDLE = json.loads(CPU_JSON)["idle"]
        CPU = f"{100 - CPU_IDLE:.2f}%"
        if CPU_IDLE == 100:
            CPU = "0%"
        if CPU_IDLE == 0:
            CPU = "100%"
    except (RunCommandError, OSError, ValueError):
        CPU = "unknown"

    # determine mem useage
    cmd = "free -m | awk 'NR==2{printf \"%s/%sMB %.2f%%\", $3,$2,$3*100/$2 }'"
    try:
        MemUsage = run_command(cmd, shell=True).stdout.strip()
    except (RunCommandError, OSError):
        MemUsage = "unknown"

    # determine disk util
    cmd = 'df -h | awk \'$NF=="/"{printf "%d/%dGB %s", $3,$2,$5}\''
    try:
        Disk = run_command(cmd, shell=True).stdout.strip()
    except (RunCommandError, OSError):
        Disk = "unknown"

    tempStr = _read_cpu_temperature()

    # determine uptime
    cmd = r"uptime -p | sed -r 's/up|,//g' | sed -r 's/\s*week[s]?/w/g' | sed -r 's/\s*day[s]?/d/g' | sed -r 's/\s*hour[s]?/h/g' | sed -r 's/\s*minute[s]?/m/g'"
    try:
        uptime = run_command(cmd, shell=True).stdout.strip()
    except (RunCommandError, OSError):
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


def is_allowed_service(service: str) -> bool:
    """Check if service is in allowed services list."""
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


def check_service_status(service: str) -> bool:
    """
    Query systemd through dbus to see if the service is running.

    You can list services from the CLI like this: systemctl list-unit-files --type=service
    """
    service_running = False
    if ".service" not in service:
        service = service + ".service"
    with _systemd_lock:
        bus, manager = _get_systemd_client()
        try:
            unit_path = manager.GetUnit(
                service,
                timeout=_SYSTEMD_DBUS_TIMEOUT_SEC,
            )
            service_proxy = bus.get_object(
                _SYSTEMD_BUS_NAME,
                object_path=unit_path,
            )
            service_props = Interface(
                service_proxy,
                dbus_interface=_SYSTEMD_PROPERTIES_INTERFACE,
            )
            service_load_state = service_props.Get(
                "org.freedesktop.systemd1.Unit",
                "LoadState",
                timeout=_SYSTEMD_DBUS_TIMEOUT_SEC,
            )
            service_active_state = service_props.Get(
                "org.freedesktop.systemd1.Unit",
                "ActiveState",
                timeout=_SYSTEMD_DBUS_TIMEOUT_SEC,
            )
            if service_load_state == "loaded" and service_active_state == "active":
                service_running = True
        except DBusException as exc:
            if exc.args and "not loaded" in str(exc.args[0]):
                return service_running
            _raise_systemd_dbus_error(
                exc,
                action="checking",
                service=service,
                missing_status=503,
            )
        except ValueError as error:
            raise ValidationError(f"{error}", status_code=400) from None
    return service_running


async def get_systemd_service_status(name: str) -> dict[str, Any]:
    """Query systemd via dbus to get the current status of an allowed service."""
    status: Any = ""
    name = name.strip().lower()
    if is_allowed_service(name):
        status = await asyncio.to_thread(check_service_status, name)
        return {"name": name, "active": status}

    raise ValidationError(
        f"{name} access is restricted or does not exist", status_code=400
    )


def stop_service(service: str) -> bool:
    """Stop a systemd service."""
    if ".service" not in service:
        service = service + ".service"
    with _systemd_lock:
        _, manager = _get_systemd_client()
        try:
            manager.StopUnit(
                service,
                "replace",
                timeout=_SYSTEMD_DBUS_TIMEOUT_SEC,
            )
            # manager.DisableUnitFiles([service], Boolean(False))
        except DBusException as exc:
            _raise_systemd_dbus_error(
                exc,
                action="stopping",
                service=service,
            )
    return False


async def stop_systemd_service(name: str) -> dict[str, Any]:
    """Stop an allowed systemd service via dbus."""
    status: Any = ""
    name = name.strip().lower()
    if is_allowed_service(name):
        status = await asyncio.to_thread(stop_service, name)
        return {"name": name, "active": status}

    raise ValidationError(
        f"stopping {name} is restricted or does not exist", status_code=400
    )


def start_service(service: str) -> bool:
    """Start a systemd service."""
    if ".service" not in service:
        service = service + ".service"
    with _systemd_lock:
        _, manager = _get_systemd_client()
        try:
            # manager.EnableUnitFiles([service], Boolean(False), Boolean(True))
            manager.StartUnit(
                service,
                "replace",
                timeout=_SYSTEMD_DBUS_TIMEOUT_SEC,
            )
        except DBusException as exc:
            _raise_systemd_dbus_error(
                exc,
                action="starting",
                service=service,
            )
    return True


async def start_systemd_service(name: str) -> dict[str, Any]:
    """Start an allowed systemd service via dbus."""
    status: Any = ""
    name = name.strip().lower()
    if is_allowed_service(name):
        status = await asyncio.to_thread(start_service, name)
        return {"name": name, "active": status}

    raise ValidationError(
        f"starting {name} is restricted or does not exist", status_code=400
    )


def restart_service(service: str) -> bool:
    """Restart a systemd service and report its status."""
    if ".service" not in service:
        service = service + ".service"
    with _systemd_lock:
        _, manager = _get_systemd_client()
        try:
            manager.RestartUnit(
                service,
                "replace",
                timeout=_SYSTEMD_DBUS_TIMEOUT_SEC,
            )
        except DBusException as exc:
            _raise_systemd_dbus_error(
                exc,
                action="restarting",
                service=service,
            )
        return check_service_status(service)


async def restart_systemd_service(name: str) -> dict[str, Any]:
    """Restart an allowed systemd service via dbus."""
    name = name.strip().lower()
    if is_allowed_service(name):
        active = await asyncio.to_thread(restart_service, name)
        return {"name": name, "active": active}

    raise ValidationError(
        f"restarting {name} is restricted or does not exist", status_code=400
    )


def _resolve_timezone() -> str:
    """Return the system IANA timezone name.

    Prefer ``timedatectl`` (the authoritative systemd value): on some images
    ``timedatectl set-timezone`` updates ``/etc/localtime`` but leaves
    ``/etc/timezone`` stale, so that file is only a fallback.
    """
    try:
        tz = run_command(
            ["timedatectl", "show", "-p", "Timezone", "--value"],
            raise_on_fail=False,
        ).stdout.strip()
        if tz:
            return tz
    except (RunCommandError, FileNotFoundError):
        pass

    tz_path = Path("/etc/timezone")
    try:
        if tz_path.exists():
            tz = tz_path.read_text().strip()
            if tz:
                return tz
    except OSError:
        pass

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

    return "UTC"


def get_datetime() -> dict[str, str | None]:
    """
    Return local date/time as ISO 8601 for API clients.

    Uses `date -Iseconds` as the canonical source because systemd's
    `timedatectl show -p LocalTime` is empty on some images (TimeUSec is used instead).
    """
    log.debug("get_datetime: resolving local time")
    try:
        local_iso = run_command(
            ["date", "-Iseconds"], raise_on_fail=True
        ).stdout.strip()
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
    except ZoneInfoNotFoundError:
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


def get_timezone() -> dict[str, str]:
    """Return the current system timezone."""
    try:
        timezone = run_command(
            ["timedatectl", "show", "-p", "Timezone", "--value"], raise_on_fail=True
        ).stdout.strip()
        return {"timezone": timezone}
    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError):
        tz_path = Path("/etc/timezone")
        if tz_path.exists():
            return {"timezone": tz_path.read_text().strip()}
        raise ValidationError("Unable to determine timezone", status_code=503) from None


def _parse_keyvalue(output: str) -> dict[str, str]:
    """Parse `key=value` lines (systemd `timedatectl` output) into a dict."""
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


def _parse_int(value: str | None) -> int | None:
    """Return an int for a numeric string, else None."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _runtime_ntp_servers() -> list[str]:
    """
    Return the runtime NTP servers currently set on systemd-timesyncd.

    These are fed in by the NetworkManager DHCP dispatcher (full image), so a
    non-empty list means timesyncd is using DHCP-provided servers. Output is
    ``as N "server"...`` from busctl.
    """
    try:
        output = run_command(
            [
                "busctl",
                "get-property",
                "org.freedesktop.timesync1",
                "/org/freedesktop/timesync1",
                "org.freedesktop.timesync1.Manager",
                "RuntimeNTPServers",
            ],
            raise_on_fail=False,
        ).stdout.strip()
    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.debug("get_ntp: RuntimeNTPServers query failed: %r", exc)
        return []

    parts = output.split(None, 2)
    if len(parts) < 2 or parts[0] != "as":
        return []
    if _parse_int(parts[1]) == 0 or len(parts) < 3:
        return []
    return [server.strip('"') for server in parts[2].split() if server.strip('"')]


def get_ntp() -> dict[str, Any]:
    """
    Return the system clock / NTP synchronization state.

    Sources systemd-timesyncd state via `timedatectl show` and
    `timedatectl show-timesync`. Never raises for a missing or unsynced clock;
    callers render whatever is available.
    """
    result: dict[str, Any] = {
        "synchronized": False,
        "ntp_service": False,
        "server_name": None,
        "server_address": None,
        "fallback_servers": [],
        "runtime_servers": [],
        "poll_interval": None,
        "frequency": None,
        "source": "unknown",
    }

    try:
        show = _parse_keyvalue(
            run_command(
                ["timedatectl", "show", "-p", "NTP", "-p", "NTPSynchronized"],
                raise_on_fail=False,
            ).stdout
        )
        result["ntp_service"] = show.get("NTP", "no").lower() == "yes"
        result["synchronized"] = show.get("NTPSynchronized", "no").lower() == "yes"
    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.debug("get_ntp: timedatectl show failed: %r", exc)

    try:
        timesync = _parse_keyvalue(
            run_command(["timedatectl", "show-timesync"], raise_on_fail=False).stdout
        )
        result["server_name"] = timesync.get("ServerName") or None
        result["server_address"] = timesync.get("ServerAddress") or None
        result["fallback_servers"] = timesync.get("FallbackNTPServers", "").split()
        result["poll_interval"] = timesync.get("PollIntervalUSec") or None
        result["frequency"] = _parse_int(timesync.get("Frequency"))
    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.debug("get_ntp: timedatectl show-timesync failed: %r", exc)

    runtime = _runtime_ntp_servers()
    result["runtime_servers"] = runtime
    if runtime:
        result["source"] = "dhcp"
    elif result["server_name"] or result["server_address"]:
        result["source"] = "default"

    log.debug("get_ntp: %s", result)
    return result


@lru_cache(maxsize=1)
def _timezone_names() -> tuple[str, ...]:
    """Load the static tzdata name set once per service process."""
    try:
        output = run_command(
            ["timedatectl", "list-timezones"], raise_on_fail=True
        ).stdout
        return tuple(line.strip() for line in output.splitlines() if line.strip())
    except (RunCommandError, subprocess.CalledProcessError, FileNotFoundError):
        raise ValidationError("Unable to list timezones", status_code=503) from None


def list_timezones() -> dict[str, list[str]]:
    """Return a fresh response around the process-cached timezone names."""
    return {"timezones": list(_timezone_names())}


def set_timezone(timezone: str) -> dict[str, str]:
    """Set the system timezone."""
    timezone = timezone.strip()
    if not timezone:
        raise ValidationError("timezone is required", status_code=400)
    if timezone not in _timezone_names():
        raise ValidationError(
            "timezone is not a supported IANA timezone",
            status_code=400,
        )
    if Path(TIME_ZONE_FILE).exists():
        run_command([TIME_ZONE_FILE, "set", timezone], raise_on_fail=True)
    else:
        run_command(["timedatectl", "set-timezone", timezone], raise_on_fail=True)
    return get_timezone()


def get_reg_domain() -> dict[str, Any]:
    """
    Return current Wi-Fi regulatory domain country code.

    Uses `wlanpi-reg-domain get` (not `show` — the script subcommand is `get`).
    Falls back to `iw reg get` when the script output is not a valid country code.
    """
    log.debug("get_reg_domain: reading regulatory domain")
    raw: str | None = None
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
                    log.debug(
                        "get_reg_domain: /etc/default/crda REGDOMAIN=%r", candidate
                    )
                    if _is_plain_country_code(candidate):
                        raw = candidate
                        source = "crda"
                        break

    if raw is None:
        try:
            iw_raw = run_command(
                ["iw", "reg", "get"], raise_on_fail=True
            ).stdout.strip()
            log.debug("get_reg_domain: iw reg get stdout=%r", iw_raw)
            raw = iw_raw
            source = "iw"
        except (
            RunCommandError,
            subprocess.CalledProcessError,
            FileNotFoundError,
        ) as exc:
            log.error("get_reg_domain: unable to read reg domain: %r", exc)
            raise ValidationError(
                f"Unable to read regulatory domain: {exc}", status_code=503
            ) from None

    country = _parse_reg_country(raw)
    reg_result = {"country": country, "raw": raw, "source": source}
    log.debug("get_reg_domain: parsed country=%r source=%r", country, source)
    if country == "unknown":
        log.warning("get_reg_domain: could not parse country from raw=%r", raw)
    return reg_result


def set_reg_domain(country: str) -> dict[str, Any]:
    """Set the Wi-Fi regulatory domain country code."""
    country = country.strip().upper()
    if len(country) != 2 or not country.isalpha():
        raise ValidationError("country must be a 2-letter code", status_code=400)
    if not is_supported_reg_domain(country):
        raise ValidationError(
            f"country {country} is not in the supported regulatory domain list",
            status_code=400,
        )
    if Path(REG_DOMAIN_FILE).exists():
        run_command(
            [REG_DOMAIN_FILE, "set", country, "--no-prompt"], raise_on_fail=True
        )
    else:
        run_command(["iw", "reg", "set", country], raise_on_fail=True)
    return get_reg_domain()


def list_reg_domains() -> dict[str, Any]:
    """Return the supported regulatory domain countries."""
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


def enable_timezone_auto() -> dict[str, Any]:
    """Enable NTP time synchronization via timedatectl."""
    run_command(["timedatectl", "set-ntp", "true"], raise_on_fail=True)
    ntp = run_command(
        ["timedatectl", "show", "-p", "NTP", "--value"],
        raise_on_fail=True,
    ).stdout.strip()
    timezone = get_timezone()["timezone"]
    return {"ntp": ntp.lower() in ("yes", "1", "true"), "timezone": timezone}


def set_ntp_enabled(enabled: bool) -> dict[str, Any]:
    """Enable or disable NTP time synchronization via timedatectl."""
    run_command(
        ["timedatectl", "set-ntp", "true" if enabled else "false"],
        raise_on_fail=True,
    )
    return get_ntp()


def reboot_system() -> dict[str, str]:
    """Initiate an immediate system reboot."""
    run_command(
        ["/usr/bin/systemctl", "reboot", "--no-block"],
        raise_on_fail=True,
        timeout=_POWER_ACTION_TIMEOUT_SEC,
    )
    return {"status": "rebooting"}


def shutdown_system() -> dict[str, str]:
    """Initiate an immediate system shutdown."""
    run_command(
        ["/usr/bin/systemctl", "poweroff", "--no-block"],
        raise_on_fail=True,
        timeout=_POWER_ACTION_TIMEOUT_SEC,
    )
    return {"status": "shutting_down"}


def get_battery() -> dict[str, Any]:
    """Return battery status if a power supply is present."""
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


def _parse_throttled(raw: str) -> dict[str, Any]:
    """Decode ``vcgencmd get_throttled`` into named flags."""
    text = raw.strip()
    if "=" in text:
        text = text.split("=", 1)[1].strip()
    try:
        value = int(text, 16)
    except ValueError:
        value = 0
    return {
        "raw": raw.strip(),
        "undervoltage": bool(value & (1 << 0)),
        "frequency_capped": bool(value & (1 << 1)),
        "throttled": bool(value & (1 << 2)),
        "soft_temperature_limit": bool(value & (1 << 3)),
        "undervoltage_occurred": bool(value & (1 << 16)),
        "frequency_capped_occurred": bool(value & (1 << 17)),
        "throttled_occurred": bool(value & (1 << 18)),
        "soft_temperature_limit_occurred": bool(value & (1 << 19)),
    }


def _get_throttled() -> dict[str, Any]:
    """Return the decoded throttling state, or an all-clear if unavailable."""
    try:
        result = run_command(
            ["/usr/bin/vcgencmd", "get_throttled"], raise_on_fail=False
        )
        raw = result.stdout.strip() or "throttled=0x0"
    except (RunCommandError, OSError):
        raw = "unavailable"
    return _parse_throttled(raw)


def _get_temperatures() -> list[dict[str, Any]]:
    """Return every hwmon/thermal temperature reading psutil can find."""
    readings: list[dict[str, Any]] = []
    try:
        sensors = psutil.sensors_temperatures()
    except Exception:
        return readings
    for name, entries in sensors.items():
        for entry in entries:
            readings.append(
                {
                    "name": name,
                    "label": entry.label or None,
                    "celsius": (
                        round(entry.current, 1) if entry.current is not None else None
                    ),
                }
            )
    return readings


def _get_ntp() -> dict[str, bool]:
    """Return whether NTP is enabled and the clock is synchronised."""
    try:
        result = run_command(
            ["timedatectl", "show", "-p", "NTP", "-p", "NTPSynchronized"],
            raise_on_fail=False,
        )
    except (RunCommandError, OSError):
        return {"enabled": False, "synchronized": False}
    return {
        "enabled": "NTP=yes" in result.stdout,
        "synchronized": "NTPSynchronized=yes" in result.stdout,
    }


def _get_load() -> dict[str, float]:
    """Return the 1/5/15 minute load averages."""
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:
        return {"one": 0.0, "five": 0.0, "fifteen": 0.0}
    return {
        "one": round(one, 2),
        "five": round(five, 2),
        "fifteen": round(fifteen, 2),
    }


def _get_swap() -> dict[str, int]:
    """Return swap usage in mebibytes."""
    try:
        swap = psutil.swap_memory()
    except Exception:
        return {"used_mb": 0, "total_mb": 0}
    mib = 1024 * 1024
    return {"used_mb": swap.used // mib, "total_mb": swap.total // mib}


def _get_rfkill() -> list[dict[str, Any]]:
    """Return the rfkill switches from sysfs."""
    entries: list[dict[str, Any]] = []
    root = Path("/sys/class/rfkill")
    if not root.exists():
        return entries
    for entry in sorted(root.iterdir()):
        try:
            name = (entry / "name").read_text(encoding="utf-8").strip()
            rtype = (entry / "type").read_text(encoding="utf-8").strip()
            soft = (entry / "soft").read_text(encoding="utf-8").strip() == "1"
            hard = (entry / "hard").read_text(encoding="utf-8").strip() == "1"
        except OSError:
            continue
        entries.append(
            {
                "name": name,
                "type": rtype,
                "soft_blocked": soft,
                "hard_blocked": hard,
            }
        )
    return entries


def get_health() -> dict[str, Any]:
    """Return a device health snapshot.

    Covers throttling/under-voltage, temperatures, NTP sync, load average,
    swap usage, and rfkill switch state.
    """
    return {
        "throttled": _get_throttled(),
        "temperatures": _get_temperatures(),
        "ntp": _get_ntp(),
        "load": _get_load(),
        "swap": _get_swap(),
        "rfkill": _get_rfkill(),
    }


def get_failed_services() -> dict[str, Any]:
    """Return the systemd units currently in the failed state."""
    try:
        result = run_command(
            ["systemctl", "--failed", "--output=json", "--no-pager"],
            raise_on_fail=False,
        )
    except (RunCommandError, OSError):
        return {"units": []}

    try:
        parsed = json.loads(result.stdout or "[]")
    except ValueError:
        return {"units": []}
    if not isinstance(parsed, list):
        return {"units": []}

    return {
        "units": [
            {
                "unit": str(item.get("unit", "")),
                "load": str(item.get("load", "")),
                "active": str(item.get("active", "")),
                "sub": str(item.get("sub", "")),
                "description": str(item.get("description", "")),
            }
            for item in parsed
            if isinstance(item, dict)
        ]
    }
