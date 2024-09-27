from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    name: str = Field(examples=["wlanpi-fpms"])
    active: bool = Field(examples=[True])


class ServiceRunning(BaseModel):
    name: str = Field(examples=["wlanpi-fpms"])
    active: bool = Field(examples=[True])
