from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScanAdapter(BaseModel):
    iface: str
    namespace: str = Field(description="Namespace name, or root for default namespace")
    label: str
    mode: Optional[str] = None


class WlanNetwork(BaseModel):
    ssid: str
    bssid: str
    signal: int
    freq: int
    key_mgmt: Optional[str] = None
    minrate: int = 1_000_000


class WlanScanResponse(BaseModel):
    selected_adapter: Optional[ScanAdapter] = Field(
        default=None, alias="selectedAdapter"
    )
    networks: list[WlanNetwork] = Field(default_factory=list)
    scanned_at: Optional[datetime] = Field(default=None, alias="scannedAt")
    needs_selection: bool = Field(default=False, alias="needsSelection")
    candidates: list[ScanAdapter] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class WlanScanErrorResponse(BaseModel):
    error: str
    candidates: list[ScanAdapter] = Field(default_factory=list)
