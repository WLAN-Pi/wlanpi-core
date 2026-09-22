"""System information and control schemas."""

from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    """Status of a systemd service."""

    name: str = Field(examples=["wlanpi-fpms"])
    active: bool = Field(examples=[True])


class ServiceRunning(BaseModel):
    """Whether a systemd service is running."""

    name: str = Field(json_schema_extra={"example": "wlanpi-fpms"})
    active: bool = Field(json_schema_extra={"example": True})


class DeviceSerial(BaseModel):
    """Device serial number."""

    serial: str = Field(json_schema_extra={"example": "133700330070513050022035384b"})


class DeviceModel(BaseModel):
    """Device model identifier."""

    model: str = Field(json_schema_extra={"example": "R4"})


class DeviceInfo(BaseModel):
    """Device identity and operating mode."""

    model: str = Field(json_schema_extra={"example": "R4"})
    name: str = Field(json_schema_extra={"example": "wlanpi-bc2"})
    hostname: str = Field(json_schema_extra={"example": "wlanpi-bc2.local"})
    software_version: str = Field(json_schema_extra={"example": "3.2.0"})
    mode: str = Field(json_schema_extra={"example": "classic"})
    wlan_management: str = Field(
        json_schema_extra={"example": "auto"},
        description=(
            "Wi-Fi management mode: auto (core manages Wi-Fi interfaces) "
            "or manual (operator owns the radios)"
        ),
    )


class DeviceStats(BaseModel):
    """Device resource usage statistics."""

    ip: str = Field(json_schema_extra={"example": "127.0.0.1"})
    cpu: str = Field(json_schema_extra={"example": "23%"})
    ram: str = Field(json_schema_extra={"example": "1022/3792MB 26.95%"})
    disk: str = Field(json_schema_extra={"example": "6/59GB 11%"})
    cpu_temp: str = Field(json_schema_extra={"example": "52.0C"})
    uptime: str = Field(json_schema_extra={"example": "1h 40m"})


class DateTimeInfo(BaseModel):
    """Device local date/time. Always parse `datetime` as ISO 8601 / RFC 3339."""

    datetime: str = Field(
        description="Local wall-clock time as ISO 8601, e.g. 2026-06-07T21:32:12+01:00",
        examples=["2026-06-07T21:32:12+01:00"],
    )
    timezone: str = Field(
        description="IANA timezone name when available, e.g. Europe/London",
        examples=["Europe/London"],
    )
    display: str | None = Field(
        default=None,
        description="Human-readable local time for UI labels; do not parse programmatically",
        examples=["Sun 2026-06-07 21:32:22 BST"],
    )
    source: str = Field(
        default="date",
        description="How datetime was obtained: date | timedatectl | fallback",
        examples=["date"],
    )


class TimezoneInfo(BaseModel):
    """Current system timezone."""

    timezone: str = Field(json_schema_extra={"example": "Europe/London"})


class TimezoneList(BaseModel):
    """Available system timezones."""

    timezones: list[str] = Field(default_factory=list)


class TimezoneSetRequest(BaseModel):
    """Request to set the system timezone."""

    timezone: str = Field(json_schema_extra={"example": "Europe/London"})


class NtpInfo(BaseModel):
    """systemd-timesyncd clock/NTP state."""

    synchronized: bool = Field(
        description="True when the system clock is synchronized",
        examples=[True],
    )
    ntp_service: bool = Field(
        description="True when the NTP service is enabled",
        examples=[True],
    )
    server_name: str | None = Field(
        default=None,
        description="NTP server name currently in use",
        examples=["2.debian.pool.ntp.org"],
    )
    server_address: str | None = Field(
        default=None,
        description="Resolved address of the NTP server currently in use",
        examples=["192.168.2.123"],
    )
    fallback_servers: list[str] = Field(
        default_factory=list,
        description="Fallback NTP servers configured for timesyncd",
    )
    runtime_servers: list[str] = Field(
        default_factory=list,
        description="Runtime NTP servers set on timesyncd (DHCP-provided)",
    )
    poll_interval: str | None = Field(
        default=None,
        description="Current poll interval as reported by timesyncd",
        examples=["32s"],
    )
    frequency: int | None = Field(
        default=None,
        description="Current clock frequency adjustment, if reported",
    )
    source: str = Field(
        default="unknown",
        description="Where the NTP servers came from: dhcp | default | unknown",
        examples=["dhcp"],
    )


class RegDomainInfo(BaseModel):
    """Wi-Fi regulatory domain. Always parse `country` (ISO 3166-1 alpha-2)."""

    country: str = Field(
        description="Two-letter country code, e.g. GB, US",
        examples=["GB"],
    )
    raw: str | None = Field(
        default=None,
        description="Underlying tool output for diagnostics; do not parse — use country",
        examples=["GB"],
    )
    source: str = Field(
        default="wlanpi-reg-domain",
        description="How country was obtained: wlanpi-reg-domain | iw | crda",
        examples=["wlanpi-reg-domain"],
    )


class RegDomainSetRequest(BaseModel):
    """Request to set the regulatory domain country code."""

    country: str = Field(
        min_length=2, max_length=2, json_schema_extra={"example": "GB"}
    )


class RegDomainCountry(BaseModel):
    """One supported regulatory domain country."""

    code: str = Field(description="ISO 3166-1 alpha-2 country code", examples=["GB"])
    name: str = Field(
        description="English display name for UI pickers", examples=["United Kingdom"]
    )


class RegDomainList(BaseModel):
    """List of supported regulatory domain countries."""

    countries: list[RegDomainCountry] = Field(default_factory=list)


class BatteryInfo(BaseModel):
    """Battery status if a power supply is present."""

    present: bool = Field(json_schema_extra={"example": True})
    capacity_percent: int | None = Field(
        default=None, json_schema_extra={"example": 85}
    )
    status: str | None = Field(
        default=None, json_schema_extra={"example": "Discharging"}
    )
    source: str | None = Field(default=None, json_schema_extra={"example": "BAT0"})


class NtpAutoInfo(BaseModel):
    """NTP automatic time synchronization status."""

    ntp: bool = Field(description="Whether NTP synchronization is enabled")
    timezone: str = Field(json_schema_extra={"example": "Europe/London"})


class PowerActionResponse(BaseModel):
    """Result of a device power action."""

    status: str = Field(examples=["rebooting", "shutting_down"])


class HotspotClients(BaseModel):
    """Connected client count for hotspot mode."""

    mode: str = Field(json_schema_extra={"example": "hotspot"})
    interface: str = Field(json_schema_extra={"example": "wlan0"})
    count: int = Field(json_schema_extra={"example": 2})


class HotspotCredentials(BaseModel):
    """Hotspot SSID and WPA passphrase."""

    mode: str = Field(json_schema_extra={"example": "hotspot"})
    ssid: str = Field(json_schema_extra={"example": "WLAN Pi abc"})
    passphrase: str = Field(json_schema_extra={"example": "example-passphrase"})
