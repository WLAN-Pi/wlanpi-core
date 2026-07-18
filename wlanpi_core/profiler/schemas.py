from typing import Optional

from pydantic import BaseModel, Field


class Status(BaseModel):
    running: bool = Field(examples=[True, False])
    ssid: Optional[str] = Field(default=None, example="Profiler 193")
    passphrase: Optional[str] = Field(
        default=None,
        example="12345678",
        description="Present when profiler AP is running; omitted when idle",
    )


class Start(BaseModel):
    success: bool = Field(examples=[True, False])


class Stop(BaseModel):
    success: bool = Field(examples=[True, False])
