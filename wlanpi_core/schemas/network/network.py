from pydantic import BaseModel, Field


class PublicIP(BaseModel):
    ip: str = Field(example="192.168.1.50")
    ip_decimal: int = Field(example=3232235826)
    country: str = Field(example="United States")
    country_iso: str = Field(example="US")
    country_eu: bool = Field(example=False)
    region_name: str = Field(example="Kansas")
    region_code: str = Field(example="KS")
    metro_code: int = Field(example=913)
    zip_code: str = Field(example="66106")
    city: str = Field(example="Kansas City")
    latitude: float = Field(example=39.1033441)
    longitude: float = Field(example=-94.6721391)
    time_zone: str = Field(example="America/Chicago")
    asn: str = Field(example="AS12345")
    asn_org: str = Field(example="INTERNET")
    hostname: str = Field(example="static.isp.net")


class Neighbors(BaseModel):
    pass
