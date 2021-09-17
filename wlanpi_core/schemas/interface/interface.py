from typing import List, Optional

from pydantic import BaseModel, Field


class Band(BaseModel):
    band: str = Field(example="2G")
    channels: List = Field(example=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])


class Channels(BaseModel):
    interface: str = Field(example="wlan0")
    bands: Optional[Band]


class Interface(BaseModel):
    mac: str = Field(example="8c:88:2a:90:25:a3")
    driver: str = Field(example="mt76x2u")
    operstate: str = Field(example="down")
    mode: str = Field(example="managed")


class Interfaces(BaseModel):
    interface: Optional[Interface]
