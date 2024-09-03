from typing import Optional, Union

from pydantic import BaseModel, Field, Extra


class PublicIP(BaseModel):
    ip: str = Field(examples=["192.168.1.50"])
    ip_decimal: int = Field(examples=[3232235826])
    country: str = Field(examples=["United States"])
    country_iso: str = Field(examples=["US"])
    country_eu: bool = Field(examples=[False])
    latitude: float = Field(examples=[39.1033441])
    longitude: float = Field(examples=[-94.6721391])
    time_zone: str = Field(examples=["America/Chicago"])
    asn: str = Field(examples=["AS12345"])
    asn_org: str = Field(examples=["INTERNET"])
    hostname: str = Field(examples=["d-192-168-1-50.paw.cpe.chicagoisp.net"])

class IPInterfaceAddress(BaseModel, extra=Extra.allow):
    family: str = Field(examples=["inet", "inet6"])
    local: str = Field(examples=["10.0.0.1"])
    prefixlen: int = Field(examples=[32, 128])
    broadcast: Optional[str] = Field(examples=["10.0.0.255"], default=None)
    anycast: Optional[str] = Field(examples=["10.0.0.255"], default=None)
    scope: Union[str, int] = Field(examples=["global", "link", "host", 3])
    dynamic: bool = Field(examples=[False, True], default=False)
    label: Optional[str] = Field(examples=["eth0", "lo"], default=None)
    valid_life_time: Optional[int] = Field(examples=[3600, None], default=None)
    preferred_life_time: Optional[int] = Field(examples=[3600, 41213, None], default=None)


class IPInterface(BaseModel, extra=Extra.allow):
    ifindex: int = Field(examples=[0])
    ifname: str = Field(examples=["eth0", "lo"])
    flags: list[str] = Field(examples=[["UP", "BROADCAST", "MULTICAST"], "LOOPBACK"])
    mtu: int = Field(examples=[1500])
    qdisc: str = Field(examples=["noqueue", "mq", "pfifo_fast", "noop"])
    operstate: str = Field(examples=["UP", "DOWN"])
    group: str = Field(examples=["default"])
    txqlen: int = Field(examples=[1000])
    link_type: str = Field(examples=["ether", "loopback"])
    address: str = Field(examples=["00:50:56:83:4f:7d"])
    broadcast: str = Field(examples=["ff:ff:ff:ff:ff:ff"])
    addr_info: list[IPInterfaceAddress] = Field(examples=[])
