import typing
from typing import Optional

from pydantic import BaseModel, Extra, Field, field_validator


class NetworkAddress(BaseModel):
    family: str = Field(examples=["inet"], default="inet")

    vlan_raw_device: Optional[str] = Field(
        alias="vlan-raw-device", examples=["eth0"], default=None
    )

    @field_validator("family")
    def validate_family(cls, v):
        if v:
            v = v.lower()

        # Only supporting inet at the moment
        assert v in ("inet",), "family must be one of 'inet'"
        return v


# class InetNetworkAddress(NetworkAddress):
class InetNetworkAddress(NetworkAddress, extra=Extra.allow):
    family: str = "inet"
    address_type: typing.Literal["loopback", "static", "manual", "dhcp"]

    # @field_validator('address_type')
    # def validate_address_type(cls, v):
    #     if v:
    #         v = v.lower()
    #     # assert v in ('loopback', 'static', 'manual', 'dhcp'), "address_type must be one of 'loopback', 'static', 'manual', 'dhcp'"
    #     print("cls: {}".format(cls.model_dump(cls)))
    #     # assert v.lower() == cls.address_type, f"address_type must be '{cls.address_type}'"
    #     return v


class InetLoopbackNetworkAddress(InetNetworkAddress):
    address_type: str = "loopback"

    @field_validator("address_type")
    def validate_own_address_type(cls, v):
        correct_address_type = "loopback"
        assert (
            v.lower() == correct_address_type
        ), f"address_type must be '{correct_address_type}'"
        return v


class InetStaticNetworkAddress(InetNetworkAddress):
    address_type: str = "static"
    address: str = Field(examples=["192.168.1.27/24"])
    metric: Optional[int] = Field(examples=[10], default=None)
    gateway: Optional[str] = Field(examples=["192.168.1.1"], default=None)
    pointopoint: Optional[str] = Field(default=None)
    hwaddress: Optional[str] = Field(examples=["12:34:56:78:9A:BC"], default=None)
    mtu: Optional[int] = Field(examples=[1500], default=None)
    scope: Optional[str] = Field(examples=["global"], default=None)
    # dns: str = Field(example="192.168.1.1")

    @field_validator("address_type")
    def validate_own_address_type(cls, v):
        correct_address_type = "static"
        assert (
            v.lower() == correct_address_type
        ), f"address_type must be '{correct_address_type}'"
        return v

    @field_validator("scope")
    def validate_scope(cls, v):
        if v:
            v = v.lower()
        assert v in (
            "global",
            "link",
            "host",
        ), "scope must be one of 'global', 'link', or 'host'"
        return v


class InetManualNetworkAddress(InetNetworkAddress):
    address_type: str = "manual"
    hwaddress: Optional[str] = Field(examples=["12:34:56:78:9A:BC"], default=None)
    mtu: Optional[int] = Field(examples=["1500"], default=None)

    @field_validator("address_type")
    def validate_own_address_type(cls, v):
        correct_address_type = "manual"
        assert (
            v.lower() == correct_address_type
        ), f"address_type must be '{correct_address_type}'"
        return v


class InetDhcpNetworkAddress(InetNetworkAddress):
    address_type: str = "dhcp"
    hostname: Optional[str] = Field(examples=["wlanpi"], default=None)
    metric: Optional[int] = Field(examples=["10"], default=None)
    leasetime: Optional[int] = Field(examples=["3600"], default=None)
    vendor: Optional[str] = Field(default=None)
    client: Optional[str] = Field(default=None)
    hwaddress: Optional[str] = Field(examples=["12:34:56:78:9A:BC"], default=None)

    @field_validator("address_type")
    def validate_own_address_type(cls, v):
        correct_address_type = "dhcp"
        assert (
            v.lower() == correct_address_type
        ), f"address_type must be '{correct_address_type}'"
        return v


class Vlan(BaseModel):
    interface: str = Field(examples=["eth0"])
    vlan_tag: int = Field(examples=[20])
    if_control: str = Field(examples=["auto"])
    # addresses: list[InetNetworkAddress] = Field()
    # addresses: list[Union[InetStaticNetworkAddress, InetDhcpNetworkAddress, InetManualNetworkAddress, InetLoopbackNetworkAddress] ] = Field()
    addresses: typing.List[
        typing.Union[
            InetStaticNetworkAddress,
            InetDhcpNetworkAddress,
            InetManualNetworkAddress,
            InetLoopbackNetworkAddress,
        ]
    ] = Field()


class NetworkConfigResponse(BaseModel):
    success: bool = True
    result: typing.Any = Field(default=None)
    errors: typing.Optional[dict] = None


NETWORK_ADDRESS_TYPES = {
    "inet": {
        "base": InetNetworkAddress,
        "loopback": InetLoopbackNetworkAddress,
        "static": InetStaticNetworkAddress,
        "manual": InetManualNetworkAddress,
        "dhcp": InetDhcpNetworkAddress,
    }
}
