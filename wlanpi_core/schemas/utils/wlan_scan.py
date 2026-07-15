from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScanAdapter(BaseModel):
    iface: str
    namespace: str = Field(description="Namespace name, or root for default namespace")
    label: str
    mode: Optional[str] = None


class BssLoad(BaseModel):
    stations: Optional[int] = None
    utilization: Optional[int] = Field(
        default=None,
        description="Channel utilisation from BSS Load (0-255, as reported by iw)",
    )


class WlanNetwork(BaseModel):
    ssid: str
    bssid: str
    signal: int
    freq: int
    key_mgmt: Optional[str] = None
    minrate: int = 1_000_000
    flags: Optional[str] = None
    primary_channel: Optional[int] = Field(default=None, alias="primaryChannel")
    channel_width: Optional[int] = Field(
        default=None,
        alias="channelWidth",
        description="MHz (20, 40, 80, 160, ...)",
    )
    secondary_channel_offset: Optional[str] = Field(
        default=None,
        alias="secondaryChannelOffset",
        description="HT secondary channel: none, above, or below control channel",
    )
    bss_load: Optional[BssLoad] = Field(default=None, alias="bssLoad")
    amendments: list[str] = Field(default_factory=list)
    raw: Optional[str] = Field(
        default=None,
        description="Full iw BSS block text when detail=full",
    )

    model_config = {"populate_by_name": True}


class WlanScanResponse(BaseModel):
    detail: str = "short"
    selected_adapter: Optional[ScanAdapter] = Field(
        default=None, alias="selectedAdapter"
    )
    networks: list[WlanNetwork] = Field(default_factory=list)
    scanned_at: Optional[datetime] = Field(default=None, alias="scannedAt")
    needs_selection: bool = Field(default=False, alias="needsSelection")
    candidates: list[ScanAdapter] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
        "extra": "forbid",
    }


class WlanScanErrorResponse(BaseModel):
    error: str
    message: Optional[str] = None
    candidates: list[ScanAdapter] = Field(default_factory=list)
