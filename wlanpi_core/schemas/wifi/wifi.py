from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PhyCapabilities(BaseModel):
    phy: str = Field(example="phy0")
    info: Optional[str] = Field(default=None, description="Raw iw phy info output")
    error: Optional[str] = Field(default=None)


class WifiCapabilitiesResponse(BaseModel):
    adapters: list[PhyCapabilities] = Field(default_factory=list)


class WifiRegulatoryResponse(BaseModel):
    country: Optional[str] = Field(default=None, example="GB")
    source: Optional[str] = Field(default=None, example="iw")
    raw: str = Field(description="Raw output of iw reg get")


class HotspotStation(BaseModel):
    mac: str
    interface: str
    signal_dbm: Optional[int] = None
    tx_bitrate: Optional[str] = None
    rx_bitrate: Optional[str] = None
    inactive_time: Optional[str] = None
    connected_time: Optional[str] = None
    authorized: Optional[str] = None
    authenticated: Optional[str] = None
    associated: Optional[str] = None

    model_config = {"extra": "allow"}


class HotspotStationsResponse(BaseModel):
    mode: str = Field(example="hotspot")
    interface: str = Field(example="wlan0")
    count: int = Field(example=1)
    stations: list[HotspotStation] = Field(default_factory=list)


class HotspotClientLink(BaseModel):
    mac: Optional[str] = None
    interface: Optional[str] = None
    signal_dbm: Optional[int] = None
    tx_bitrate: Optional[str] = None
    rx_bitrate: Optional[str] = None
    inactive_time: Optional[str] = None
    connected_time: Optional[str] = None
    authorized: Optional[str] = None
    authenticated: Optional[str] = None
    associated: Optional[str] = None


class HotspotClientLinkResponse(BaseModel):
    mode: str = Field(example="hotspot")
    interface: str = Field(example="wlan0")
    count: int = Field(example=1)
    links: list[HotspotClientLink] = Field(default_factory=list)
