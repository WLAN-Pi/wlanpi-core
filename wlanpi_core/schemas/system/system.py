from typing import Optional

from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    name: str = Field(examples=["wlanpi-fpms"])
    active: bool = Field(examples=[True])


class ServiceRunning(BaseModel):
    name: str = Field(example="wlanpi-fpms")
    active: bool = Field(example=True)


class DeviceSerial(BaseModel):
    serial: str = Field(example="133700330070513050022035384b")


class DeviceModel(BaseModel):
    model: str = Field(example="R4")


class DeviceInfo(BaseModel):
    model: str = Field(example="R4")
    name: str = Field(example="wlanpi-bc2")
    hostname: str = Field(example="wlanpi-bc2.local")
    software_version: str = Field(example="3.2.0")
    mode: str = Field(example="classic")


class DeviceStats(BaseModel):
    ip: str = Field(example="127.0.0.1")
    cpu: str = Field(example="23%")
    ram: str = Field(example="1022/3792MB 26.95%")
    disk: str = Field(example="6/59GB 11%")
    cpu_temp: str = Field(example="1h 40m")
    uptime: str = Field(example="1h 40m")


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
    display: Optional[str] = Field(
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
    timezone: str = Field(example="Europe/London")


class TimezoneList(BaseModel):
    timezones: list[str] = Field(default_factory=list)


class TimezoneSetRequest(BaseModel):
    timezone: str = Field(example="Europe/London")


class RegDomainInfo(BaseModel):
    """WiFi regulatory domain. Always parse `country` (ISO 3166-1 alpha-2)."""

    country: str = Field(
        description="Two-letter country code, e.g. GB, US",
        examples=["GB"],
    )
    raw: Optional[str] = Field(
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
    country: str = Field(example="GB", min_length=2, max_length=2)


class RegDomainCountry(BaseModel):
    code: str = Field(description="ISO 3166-1 alpha-2 country code", examples=["GB"])
    name: str = Field(description="English display name for UI pickers", examples=["United Kingdom"])


class RegDomainList(BaseModel):
    countries: list[RegDomainCountry] = Field(default_factory=list)


class BatteryInfo(BaseModel):
    present: bool = Field(example=True)
    capacity_percent: Optional[int] = Field(default=None, example=85)
    status: Optional[str] = Field(default=None, example="Discharging")
    source: Optional[str] = Field(default=None, example="BAT0")
