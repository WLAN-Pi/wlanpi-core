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


class Stop(BaseModel):
    """Result of stopping the profiler."""

    success: bool = Field(examples=[True, False])
