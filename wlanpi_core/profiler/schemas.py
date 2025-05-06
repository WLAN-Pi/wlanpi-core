from pydantic import BaseModel, Field


class Status(BaseModel):
    active: bool = Field(examples=["true", "false"])
    ssid: str = Field(example="Profiler 193")
    passphrase: str = Field(example="12345678")


class Start(BaseModel):
    success: bool = Field(examples=["true", "false"])


class Stop(BaseModel):
    success: bool = Field(examples=["true", "false"])
