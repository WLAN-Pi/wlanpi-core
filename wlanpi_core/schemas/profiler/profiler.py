import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Features(BaseModel):
    dot11k: int = Field(example=1)
    dot11r: int = Field(example=0)
    dot11v: int = Field(example=1)
    dot11w: int = Field(example=1)
    dot11n: int = Field(example=1)
    dot11n_nss: int = Field(example=2)
    dot11ac: int = Field(example=1)
    dot11ac_nss: int = Field(example=2)
    dot11ac_160_mhz: int = Field(exmaple=0)
    dot11ac_su_bf: int = Field(example=0)
    dot11ac_mu_bf: int = Field(example=0)
    dot11ax: int = Field(example=1)
    dot11ax_nss: int = Field(example=2)
    dot11ax_mcs: str = Field(example="0-11")
    dot11ax_twt: int = Field(example=0)
    dot11ax_uora: int = Field(example=0)
    dot11ax_bsr: int = Field(example=0)
    dot11ax_spatial_reuse: int = Field(example=0)
    dot11ax_punctured_preamble: int = Field(example=0)
    dot11ax_he_er_su_ppdu: int = Field(example=0)
    dot11ax_six_ghz: int = Field(exmaple=0)
    dot11ax_160_mhz: int = Field(exmaple=0)
    max_power: int = Field(example=14)
    min_power: int = Field(example=0)
    supported_channels: List = Field(example=[36, 40, 44, 48])


class Capabilities(BaseModel):
    band: int = Field(example=5)
    capture_channel: int = Field(example=36)
    features: Features
    pcap: str
    date_created: datetime = Field(example="1993-07-23T10:20:30.400+02:30")


class Profile(BaseModel):
    id: uuid.UUID = Field(example="349279d5-7b65-43d6-8cd9-047ea4e5ebe5")
    profile_id: int = Field(example=1)
    schema_version: int = Field(example=1)
    profiler_version: str = Field(example="1.0.6")
    mac: str = Field(example="fa-7b-4b-6d-26-bb")
    is_laa: bool = Field(example=True)
    manuf: Optional[str] = Field(example="Apple")
    name: Optional[str] = Field(example="iPhone 12 Pro Max")
    description: Optional[str] = Field(example="the Big Phone")
    dateCreated: datetime = Field(example="1993-07-23T10:20:30.400+02:30")
    lastModified: datetime = Field(example="1993-07-23T10:20:30.400+02:30")
    capabilites: List[Capabilities]


class Profiles(BaseModel):
    profiles: List[Profile]
