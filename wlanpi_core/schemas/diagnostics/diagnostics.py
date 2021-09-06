from typing import Optional

from pydantic import BaseModel, Field


class Diagnostics(BaseModel):
    regdomain: list = Field(example='["country US: DFS-FCC"]')
    tcpdump: bool = Field(example="true")
    iw: bool = Field(example="true")
    ip: bool = Field(example="true")
    ifconfig: bool = Field(example="true")
    airmon_ng: bool = Field(example="true")


class Interface(BaseModel):
    mac: str = Field(example="8c:88:2a:90:25:a3")
    driver: str = Field(example="mt76x2u")
    operstate: str = Field(example="down")
    mode: str = Field(example="managed")


class Interfaces(BaseModel):
    interface: Optional[Interface]
