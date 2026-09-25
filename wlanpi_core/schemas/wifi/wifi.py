"""Wi-Fi capabilities, regulatory, and hotspot station schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PhyCapabilities(BaseModel):
    """Capabilities reported by one Wi-Fi PHY."""

    phy: str = Field(json_schema_extra={"example": "phy0"})
    namespace: str | None = Field(
        default=None,
        description=(
            "Network namespace the radio is in, or null for the root namespace. "
            "A network configuration can move a radio into a namespace."
        ),
    )
    info: str | None = Field(default=None, description="Raw iw phy info output")
    error: str | None = Field(default=None)


class WifiCapabilitiesResponse(BaseModel):
    """Capabilities for each adapter PHY."""

    adapters: list[PhyCapabilities] = Field(default_factory=list)


class WifiRegulatoryResponse(BaseModel):
    """Wi-Fi regulatory domain information."""

    country: str | None = Field(default=None, json_schema_extra={"example": "GB"})
    source: str | None = Field(default=None, json_schema_extra={"example": "iw"})
    raw: str = Field(description="Raw output of iw reg get")


class HotspotStation(BaseModel):
    """A station connected to the hotspot AP."""

    mac: str
    interface: str
    signal_dbm: int | None = None
    tx_bitrate: str | None = None
    rx_bitrate: str | None = None
    inactive_time: str | None = None
    connected_time: str | None = None
    authorized: str | None = None
    authenticated: str | None = None
    associated: str | None = None

    model_config = {"extra": "allow"}


class HotspotStationsResponse(BaseModel):
    """List of stations connected to the hotspot AP."""

    mode: str = Field(json_schema_extra={"example": "hotspot"})
    interface: str = Field(json_schema_extra={"example": "wlan0"})
    count: int = Field(json_schema_extra={"example": 1})
    stations: list[HotspotStation] = Field(default_factory=list)


class HotspotClientLink(BaseModel):
    """Per-client link statistics for a hotspot station."""

    mac: str | None = None
    interface: str | None = None
    signal_dbm: int | None = None
    tx_bitrate: str | None = None
    rx_bitrate: str | None = None
    inactive_time: str | None = None
    connected_time: str | None = None
    authorized: str | None = None
    authenticated: str | None = None
    associated: str | None = None


class HotspotClientLinkResponse(BaseModel):
    """Link statistics for all hotspot AP clients."""

    mode: str = Field(json_schema_extra={"example": "hotspot"})
    interface: str = Field(json_schema_extra={"example": "wlan0"})
    count: int = Field(json_schema_extra={"example": 1})
    links: list[HotspotClientLink] = Field(default_factory=list)
