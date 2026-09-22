"""Response models for GET /network/config/status (`iw dev` per namespace)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, RootModel


class NamespaceStatusError(BaseModel):
    """Error marker when a namespace could not be queried."""

    error: str = Field(
        description="Namespace could not be queried (corrupted netns, exec failure, etc.)"
    )


class IwInterfaceStatus(BaseModel):
    """Parsed `iw dev` fields for one interface (extra keys allowed)."""

    model_config = ConfigDict(extra="allow")

    type: str | None = Field(
        default=None, description="Interface type/mode, e.g. managed, monitor, AP"
    )
    addr: str | None = Field(default=None, description="MAC address")
    ssid: str | None = None
    channel: str | None = None
    wiphy: str | None = None


NamespaceStatus = dict[str, IwInterfaceStatus] | NamespaceStatusError


class NetworkConfigStatus(RootModel[dict[str, NamespaceStatus]]):
    """
    Per-namespace adapter layout from `iw dev`.

    Keys are `root` plus each network namespace name. Values are either a map of
    interface name → parsed `iw` fields, or `{ "error": "…" }` when that namespace
    could not be queried.
    """
