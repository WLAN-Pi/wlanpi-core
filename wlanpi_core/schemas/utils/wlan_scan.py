"""WLAN scan schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ScanAdapter(BaseModel):
    """A monitor adapter candidate for scanning."""

    iface: str
    namespace: str = Field(description="Namespace name, or root for default namespace")
    label: str
    mode: str | None = None


class BssLoad(BaseModel):
    """Channel utilisation reported by the BSS Load element."""

    stations: int | None = None
    utilization: int | None = Field(
        default=None,
        description="Channel utilisation from BSS Load (0-255, as reported by iw)",
    )


class WlanNetwork(BaseModel):
    """One detected WLAN network (BSS)."""

    ssid: str
    bssid: str
    signal: int
    freq: int
    key_mgmt: str | None = None
    minrate: int = 1_000_000
    flags: str | None = None
    primary_channel: int | None = Field(default=None, alias="primaryChannel")
    channel_width: int | None = Field(
        default=None,
        alias="channelWidth",
        description="MHz (20, 40, 80, 160, ...)",
    )
    secondary_channel_offset: str | None = Field(
        default=None,
        alias="secondaryChannelOffset",
        description="HT secondary channel: none, above, or below control channel",
    )
    bss_load: BssLoad | None = Field(default=None, alias="bssLoad")
    amendments: list[str] = Field(default_factory=list)
    raw: str | None = Field(
        default=None,
        description="Full iw BSS block text when detail=full",
    )

    model_config = {"populate_by_name": True}


class WlanScanResponse(BaseModel):
    """Result of a WLAN scan."""

    detail: str = "short"
    selected_adapter: ScanAdapter | None = Field(default=None, alias="selectedAdapter")
    networks: list[WlanNetwork] = Field(default_factory=list)
    scanned_at: datetime | None = Field(default=None, alias="scannedAt")
    needs_selection: bool = Field(default=False, alias="needsSelection")
    candidates: list[ScanAdapter] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
        "extra": "forbid",
    }


class WlanScanErrorResponse(BaseModel):
    """Error result of a WLAN scan."""

    error: str = Field(
        description=(
            "Machine-readable code: `NO_SCAN_ADAPTER`, `SCAN_IN_PROGRESS` or "
            "`MONITOR_IN_USE`"
        ),
        examples=["NO_SCAN_ADAPTER", "SCAN_IN_PROGRESS", "MONITOR_IN_USE"],
    )
    message: str | None = Field(
        default=None,
        description="Human-readable detail (set for SCAN_IN_PROGRESS and MONITOR_IN_USE)",
        examples=["A scan is already in progress on wlan0 in root"],
    )
    candidates: list[ScanAdapter] = Field(
        default_factory=list,
        description="Present for NO_SCAN_ADAPTER; usually empty",
    )
