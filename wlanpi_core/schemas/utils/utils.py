# flake8: noqa: D106

from typing import Optional

from pydantic import BaseModel, Field


class ReachabilityTest(BaseModel):
    ping_google: str = Field(example="12.345ms", alias="Ping Google")
    browse_google: str = Field(examples=["OK", "FAIL"], alias="Browse Google")
    ping_gateway: str = Field(example="12.345ms", alias="Ping Gateway")
    dns_server_1_resolution: Optional[str] = Field(
        None, examples=["OK", "FAIL"], alias="DNS Server 1 Resolution"
    )
    dns_server_2_resolution: Optional[str] = Field(
        None, examples=["OK", "FAIL"], alias="DNS Server 2 Resolution"
    )
    dns_server_3_resolution: Optional[str] = Field(
        None, examples=["OK", "FAIL"], alias="DNS Server 3 Resolution"
    )
    arping_gateway: str = Field(example="12.345ms", alias="Arping Gateway")

    class Config:
        populate_by_name = True


class SpeedTest(BaseModel):
    ip_address: str = Field(example="1.2.3.4")
    download_speed: str = Field(example="12.34 Mbps")
    upload_speed: str = Field(example="1.23 Mbps")


class PortBlinkerState(BaseModel):
    status: str = Field(example="success")
    action: str = Field(examples=["on", "off"])


class Usb(BaseModel):
    interfaces: list = Field()


class Ufw(BaseModel):
    status: str = Field()
    ports: list = Field()
