"""Schemas for network information endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PublicIpInfo(BaseModel):
    """Public IP probe output."""

    info: list[str] = Field(
        default_factory=list,
        description="Lines of text from the public IP probe script",
    )
    error: str | None = None


class InterfaceSummary(BaseModel):
    """Summary of one interface's status and address."""

    status: str | None = Field(default=None, examples=["UP", "DOWN"])
    ip: str | None = Field(
        default=None,
        examples=["192.168.1.10", "-", "Monitor"],
        description="IPv4 address, `-` when none, or `Monitor` for monitor-mode WLAN",
    )


class WlanInterfaceSummary(BaseModel):
    """Summary of one WLAN interface."""

    driver: str | None = None
    addr: str | None = Field(default=None, description="MAC without colons, uppercase")
    mode: str | None = Field(default=None, description="WLAN interface mode")
    ssid: str | None = None
    freq: int | None = Field(default=None, description="Centre frequency MHz")
    channel: int | None = None


class InfoLinesSection(BaseModel):
    """Section of human-readable info lines."""

    info: list[str] = Field(default_factory=list)
    error: str | None = Field(
        default=None, description="Present when the section could not be populated"
    )


class NetworkInfo(BaseModel):
    """Aggregated network information."""

    interfaces: dict[str, InterfaceSummary | str] = Field(
        description=(
            "Per-interface ifconfig summary (`status`, `ip`). On failure the dict "
            "may contain only an `error` string key instead of interface entries."
        ),
    )
    wlan_interfaces: dict[str, WlanInterfaceSummary] = Field(
        description="Per-WLAN-interface summary from `iw` / `ethtool`",
    )
    eth0_ipconfig_info: InfoLinesSection
    vlan_info: InfoLinesSection
    lldp_neighbour_info: InfoLinesSection
    cdp_neighbour_info: InfoLinesSection
    public_ip: InfoLinesSection
