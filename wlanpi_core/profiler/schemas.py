"""Response schemas for the profiler endpoints."""

from pydantic import BaseModel, Field


class Status(BaseModel):
    """Profiler status and beaconing credentials."""

    running: bool = Field(examples=[True, False])
    ssid: str | None = Field(
        default=None, json_schema_extra={"example": "Profiler 193"}
    )
    passphrase: str | None = Field(
        default=None,
        json_schema_extra={"example": "12345678"},
        description="Present when profiler AP is running; omitted when idle",
    )


class Start(BaseModel):
    """Result of starting the profiler."""

    success: bool = Field(examples=[True, False])
    reason: str | None = Field(
        default=None,
        examples=["country_code_detection", "starting"],
        description="Why it did not start, or `starting` if still starting",
    )
    message: str | None = Field(
        default=None, description="Human-readable detail for `reason`"
    )


class Stop(BaseModel):
    """Result of stopping the profiler."""

    success: bool = Field(examples=[True, False])


class Purge(BaseModel):
    """What purging the profiler data removed."""

    files: int = Field(examples=[12], description="Files and symlinks removed")
    bytes: int = Field(examples=[48213], description="Total size of those files")
