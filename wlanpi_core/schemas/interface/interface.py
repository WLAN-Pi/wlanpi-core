from typing import List

from pydantic import BaseModel, Field


class Frequencies(BaseModel):
    freq: int = Field(example=2412)
    widths: List = Field(example=["20", "40+"])


class Wiphy(BaseModel):
    phy: str = Field(example="phy0")
    interface: str = Field(example="wlan0")
    frequencies: List[Frequencies]


class Wiphys(BaseModel):
    wiphys: List[Wiphy]
