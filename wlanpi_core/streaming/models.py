"""Validated command payloads for the packet-capture WebSocket."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, RootModel, field_validator

from wlanpi_core.utils.validation import (
    validate_interface_name,
    validate_wifi_frequency,
)

_CAPTURE_INTERFACE_RE = re.compile(r"^wlanpi[0-9]{1,3}$")
_CAPTURE_WIDTHS = {20, 40, 80, 160}
_MAX_CAPTURE_INTERFACES = 8
_MAX_CAPTURE_CHANNELS = 128
_MIN_DWELL_TIME_MS = 50
_MAX_DWELL_TIME_MS = 60_000
_MAX_PCAP_FILTER_BYTES = 1024


def validate_capture_interface(value: str) -> str:
    value = validate_interface_name(value)
    if not _CAPTURE_INTERFACE_RE.fullmatch(value):
        raise ValueError("capture interface must use the wlanpiN monitor name")
    return value


def validate_capture_frequency(value: int) -> int:
    return validate_wifi_frequency(value)


def validate_capture_width(value: int) -> int:
    if isinstance(value, bool) or value not in _CAPTURE_WIDTHS:
        raise ValueError("capture width must be one of 20, 40, 80, or 160 MHz")
    return value


def validate_pcap_filter(value: Optional[str]) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("pcap_filter must be a string")
    if len(value.encode("utf-8")) > _MAX_PCAP_FILTER_BYTES:
        raise ValueError("pcap_filter is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("pcap_filter must not contain control characters")
    return value


class CaptureChannel(BaseModel):
    freq: int
    width: int

    model_config = {"extra": "forbid"}

    @field_validator("freq")
    @classmethod
    def validate_frequency_field(cls, value: int) -> int:
        return validate_capture_frequency(value)

    @field_validator("width")
    @classmethod
    def validate_width_field(cls, value: int) -> int:
        return validate_capture_width(value)


class CaptureInterfaceConfig(BaseModel):
    channels: list[CaptureChannel] = Field(
        default_factory=list,
        max_length=_MAX_CAPTURE_CHANNELS,
    )
    dwell_time: int = Field(
        default=100,
        ge=_MIN_DWELL_TIME_MS,
        le=_MAX_DWELL_TIME_MS,
    )

    model_config = {"extra": "forbid"}


class CaptureConfigurations(RootModel[dict[str, CaptureInterfaceConfig]]):
    @field_validator("root")
    @classmethod
    def validate_interfaces(
        cls, value: dict[str, CaptureInterfaceConfig]
    ) -> dict[str, CaptureInterfaceConfig]:
        if not value:
            raise ValueError("at least one capture interface is required")
        if len(value) > _MAX_CAPTURE_INTERFACES:
            raise ValueError("too many capture interfaces")
        for interface in value:
            validate_capture_interface(interface)
        return value


class CaptureStart(BaseModel):
    interfaces: list[str] = Field(
        min_length=1,
        max_length=_MAX_CAPTURE_INTERFACES,
    )
    pcap_filter: str = ""

    model_config = {"extra": "forbid"}

    @field_validator("interfaces")
    @classmethod
    def validate_interfaces_field(cls, value: list[str]) -> list[str]:
        validated = [validate_capture_interface(interface) for interface in value]
        if len(set(validated)) != len(validated):
            raise ValueError("capture interfaces must be unique")
        return validated

    @field_validator("pcap_filter", mode="before")
    @classmethod
    def validate_filter_field(cls, value: Optional[str]) -> str:
        return validate_pcap_filter(value)
