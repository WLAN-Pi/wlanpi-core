from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    name: str = Field(example="wlanpi-fpms")
    active: bool = Field(example=True)


class ServiceRunning(BaseModel):
    name: str = Field(example="wlanpi-fpms")
    active: bool = Field(example=True)
