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


class ThrottleInfo(BaseModel):
    """Raspberry Pi throttling and under-voltage flags from ``vcgencmd``."""

    raw: str = Field(json_schema_extra={"example": "throttled=0x0"})
    undervoltage: bool = Field(description="Under-voltage currently detected")
    frequency_capped: bool = Field(description="ARM frequency currently capped")
    throttled: bool = Field(description="Currently throttled")
    soft_temperature_limit: bool = Field(description="Soft temperature limit active")
    undervoltage_occurred: bool = Field(description="Under-voltage has occurred")
    frequency_capped_occurred: bool = Field(
        description="ARM frequency capping has occurred"
    )
    throttled_occurred: bool = Field(description="Throttling has occurred")
    soft_temperature_limit_occurred: bool = Field(
        description="Soft temperature limit has occurred"
    )


class TemperatureReading(BaseModel):
    """One temperature sensor reading."""

    name: str = Field(json_schema_extra={"example": "cpu_thermal-virtual-0"})
    label: str | None = Field(default=None, json_schema_extra={"example": "temp1"})
    celsius: float | None = Field(default=None, json_schema_extra={"example": 63.8})


class NtpStatus(BaseModel):
    """NTP enablement and synchronisation state."""

    enabled: bool = Field(description="Whether NTP synchronisation is enabled")
    synchronized: bool = Field(
        description="Whether the clock is currently synchronised"
    )


class LoadAverage(BaseModel):
    """System load average over 1, 5, and 15 minutes."""

    one: float
    five: float
    fifteen: float


class SwapUsage(BaseModel):
    """Swap usage in mebibytes."""

    used_mb: int
    total_mb: int


class RfkillState(BaseModel):
    """One rfkill switch."""

    name: str = Field(json_schema_extra={"example": "phy0"})
    type: str = Field(json_schema_extra={"example": "wlan"})
    soft_blocked: bool
    hard_blocked: bool


class Health(BaseModel):
    """Device health snapshot: throttling, thermals, time, load, and radios."""

    throttled: ThrottleInfo
    temperatures: list[TemperatureReading] = Field(default_factory=list)
    ntp: NtpStatus
    load: LoadAverage
    swap: SwapUsage
    rfkill: list[RfkillState] = Field(default_factory=list)


class FailedService(BaseModel):
    """A systemd unit currently in the failed state."""

    unit: str = Field(json_schema_extra={"example": "bt-agent.service"})
    load: str = Field(json_schema_extra={"example": "loaded"})
    active: str = Field(json_schema_extra={"example": "failed"})
    sub: str = Field(json_schema_extra={"example": "failed"})
    description: str = Field(json_schema_extra={"example": "Bluetooth Auth Agent"})


class FailedServices(BaseModel):
    """Failed systemd units."""

    units: list[FailedService] = Field(default_factory=list)
