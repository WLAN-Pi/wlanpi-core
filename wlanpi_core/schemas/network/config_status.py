"""Response models for GET /network/config/status (`iw dev` per namespace)."""
from __future__ import annotations

from typing import Dict, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel


class NamespaceStatusError(BaseModel):
    error: str = Field(
        description="Namespace could not be queried (corrupted netns, exec failure, etc.)"
    )


class IwInterfaceStatus(BaseModel):
    """Parsed `iw dev` fields for one interface (extra keys allowed)."""

    model_config = ConfigDict(extra="allow")

    type: Optional[str] = Field(
        default=None, description="Interface type/mode, e.g. managed, monitor, AP"
    )
    addr: Optional[str] = Field(default=None, description="MAC address")
    ssid: Optional[str] = None
    channel: Optional[str] = None
    wiphy: Optional[str] = None


NamespaceStatus = Union[Dict[str, IwInterfaceStatus], NamespaceStatusError]


class NetworkConfigStatus(
    RootModel[Dict[str, NamespaceStatus]]
):
    """
    Per-namespace adapter layout from `iw dev`.

    Keys are `root` plus each network namespace name. Values are either a map of
    interface name → parsed `iw` fields, or `{ "error": "…" }` when that namespace
    could not be queried.
    """
