"""Shared error and status response models for OpenAPI."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    """Simple human-readable message response."""

    detail: str = Field(description="Human-readable error or status message")


class ApiErrorResponse(BaseModel):
    """Machine-readable API error response."""

    error: str = Field(description="Machine-readable error code, e.g. NO_SCAN_ADAPTER")
    message: str | None = Field(
        default=None, description="Optional human-readable detail"
    )


class DeprecatedEndpointResponse(BaseModel):
    """Body returned by deprecated endpoints."""

    error: str = Field(default="ENDPOINT_DEPRECATED", examples=["ENDPOINT_DEPRECATED"])
    message: str = Field(
        description="What to call instead",
        examples=[
            "Use POST /api/v1/network/config/ then POST /api/v1/network/config/activate/{id}"
        ],
    )
    replacement: str = Field(
        description="Canonical replacement path (without host)",
        examples=["/api/v1/network/config/"],
    )


class ScanNeedsSelectionResponse(BaseModel):
    """Scan deferred until a monitor adapter is chosen."""

    error: str = Field(default="NEEDS_SELECTION", examples=["NEEDS_SELECTION"])
    candidates: list[dict[str, Any]] = Field(
        description="Monitor adapters the client must choose from before retrying scan"
    )


class ScanInProgressResponse(BaseModel):
    """A scan is already running on the selected adapter."""

    error: str = Field(
        default="SCAN_IN_PROGRESS", examples=["SCAN_IN_PROGRESS", "MONITOR_IN_USE"]
    )
    message: str = Field(
        description="Which adapter is already scanning, or which capture blocks it",
        examples=["A scan is already in progress on wlan0 in root"],
    )


class ScanNoAdapterResponse(BaseModel):
    """No suitable scan adapter is available."""

    error: str = Field(default="NO_SCAN_ADAPTER", examples=["NO_SCAN_ADAPTER"])
    candidates: list[dict[str, Any]] = Field(default_factory=list)
