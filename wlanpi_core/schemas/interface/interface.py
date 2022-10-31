from typing import List

from pydantic import BaseModel, Field


class Frequencies(BaseModel):
    freq: int = Field(example=2412)
    widths: List = Field(example=["20", "40+"])


class Wiphy(BaseModel):
    phy: str = Field(example="phy0")
    interface: str = Field(example="wlan0")
    mac: str = Field(example="e0:e1:a9:00:00:00")
    driver: str = Field(example="mt7921u")
    operstate: str = Field(example="up")
    mode: str = Field(example="monitor")
    frequencies: List[Frequencies]


class Wiphys(BaseModel):
    wiphys: List[Wiphy]


