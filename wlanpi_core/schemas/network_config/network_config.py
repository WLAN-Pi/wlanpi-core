from typing import Union, Optional

from pydantic import BaseModel, Field, field_validator

class NetworkAddress(BaseModel):
    family: str = Field(example="inet", default="inet")

    @field_validator('family')
    def validate_family(cls, v):
        if v:
            v = v.lower()

        # Only supporting inet at the moment
        assert v in ('inet',), "family must be one of 'inet'"
        return v

class InetNetworkAddress(NetworkAddress):
    family: str = "inet"
    type: str = Field(example="dhcp")

    @field_validator('type')
    def validate_type(cls, v):
        if v:
            v = v.lower()
        assert v in ('loopback', 'static', 'manual', 'dhcp'), "type must be one of 'loopback', 'static', 'manual', 'dhcp'"
        return v


class InetLoopbackNetworkAddress(InetNetworkAddress):
    type: str = "loopback"

class InetStaticNetworkAddress(InetNetworkAddress):
    type: str = 'static'

    address: str = Field(example="192.168.1.27/24")
    metric: Optional[int] = Field(example="10")
    gateway: Optional[str] = Field(example="192.168.1.1")
    pointopoint: Optional[str] = Field(example="192.168.1.1")
    hwaddress: Optional[str] = Field(example="12:34:56:78:9A:BC")
    mtu: Optional[int] = Field(example="1500")
    scope: Optional[str] = Field(example="global")
    # dns: str = Field(example="192.168.1.1")

    @field_validator('scope')
    def validate_scope(cls, v):
        if v:
            v = v.lower()
        assert v in ('global', 'link', 'host'), "scope must be one of 'global', 'link', or 'host'"
        return v

class InetManualNetworkAddress(InetNetworkAddress):
    type: str = "manual"
    hwaddress: Optional[str] = Field(example="12:34:56:78:9A:BC")
    mtu: Optional[int] = Field(example="1500")

class InetDhcpNetworkAddress(InetNetworkAddress):
    type: str = "dhcp"
    hostname: Optional[str] = Field(example="wlanpi")
    metric: Optional[int] = Field(example="10")
    leasetime: Optional[int] = Field(example="3600")
    vendor: Optional[str] = Field()
    client: Optional[str] = Field()
    hwaddress: Optional[str] = Field(example="12:34:56:78:9A:BC")

class Vlan(BaseModel):
    interface: str = Field(example="eth0")
    vlan_tag: int = Field(example=20)
    if_control: str = Field(example="auto")
    addresses: list[InetNetworkAddress] = Field()
