from __future__ import annotations

from typing import Dict, Optional, Union

from pydantic import BaseModel, Field


class PublicIpInfo(BaseModel):
    info: list[str] = Field(
        default_factory=list,
        description="Lines of text from the public IP probe script",
    )
    error: Optional[str] = None


class InterfaceSummary(BaseModel):
    status: Optional[str] = Field(default=None, examples=["UP", "DOWN"])
    ip: Optional[str] = Field(
        default=None,
        examples=["192.168.1.10", "-", "Monitor"],
        description="IPv4 address, `-` when none, or `Monitor` for monitor-mode WLAN",
    )


class WlanInterfaceSummary(BaseModel):
    driver: Optional[str] = None
    addr: Optional[str] = Field(
        default=None, description="MAC without colons, uppercase"
    )
    mode: Optional[list[str]] = Field(
        default=None,
        description="WLAN mode as a one-element list (legacy wire format from iw parsing)",
    )
    ssid: Optional[str] = None
    freq: Optional[int] = Field(default=None, description="Centre frequency MHz")
    channel: Optional[int] = None


class InfoLinesSection(BaseModel):
    info: list[str] = Field(default_factory=list)
    error: Optional[str] = Field(
        default=None, description="Present when the section could not be populated"
    )


class NetworkInfo(BaseModel):
    interfaces: Dict[str, Union[InterfaceSummary, str]] = Field(
        description=(
            "Per-interface ifconfig summary (`status`, `ip`). On failure the dict "
            "may contain only an `error` string key instead of interface entries."
        ),
    )
    wlan_interfaces: Dict[str, WlanInterfaceSummary] = Field(
        description="Per-WLAN-interface summary from `iw` / `ethtool`",
    )
    eth0_ipconfig_info: InfoLinesSection
    vlan_info: InfoLinesSection
    lldp_neighbour_info: InfoLinesSection
    cdp_neighbour_info: InfoLinesSection
    public_ip: InfoLinesSection
