"""Schemas for network address configuration."""

import typing
from typing import Any

from pydantic import BaseModel, Field, field_validator


class NetworkAddress(BaseModel):
    """Base network address with an address family."""

    family: str = Field(examples=["inet"], default="inet")

    vlan_raw_device: str | None = Field(
        alias="vlan-raw-device", examples=["eth0"], default=None
    )

    @field_validator("family")
    def validate_family(cls, v: str) -> str:
        """Validate and normalise the address family."""
        if v:
            v = v.lower()

        # Only supporting inet at the moment
        assert v in ("inet",), "family must be one of 'inet'"
        return v


# class InetNetworkAddress(NetworkAddress):
class InetNetworkAddress(NetworkAddress, extra="allow"):
    """IPv4 network address with an address type."""

    family: str = "inet"
    address_type: str

    # @field_validator('address_type')
    # def validate_address_type(cls, v):
    #     if v:
    #         v = v.lower()
    #     # assert v in ('loopback', 'static', 'manual', 'dhcp'), "address_type must be one of 'loopback', 'static', 'manual', 'dhcp'"
    #     print("cls: {}".format(cls.model_dump(cls)))
    #     # assert v.lower() == cls.address_type, f"address_type must be '{cls.address_type}'"
    #     return v


class InetLoopbackNetworkAddress(InetNetworkAddress):
    """Loopback network address."""

    address_type: str = "loopback"

    @field_validator("address_type")
    def validate_own_address_type(cls, v: str) -> str:
        """Ensure the address type is loopback."""
        correct_address_type = "loopback"
        assert v.lower() == correct_address_type, (
            f"address_type must be '{correct_address_type}'"
        )
        return v


class InetStaticNetworkAddress(InetNetworkAddress):
    """Static network address with optional gateway and MTU."""

    address_type: str = "static"
    address: str = Field(examples=["192.168.1.27/24"])
    metric: int | None = Field(examples=[10], default=None)
    gateway: str | None = Field(examples=["192.168.1.1"], default=None)
    pointopoint: str | None = Field(default=None)
    hwaddress: str | None = Field(examples=["12:34:56:78:9A:BC"], default=None)
    mtu: int | None = Field(examples=[1500], default=None)
    scope: str | None = Field(examples=["global"], default=None)
    # dns: str = Field(json_schema_extra={"example": "192.168.1.1"})

    @field_validator("address_type")
    def validate_own_address_type(cls, v: str) -> str:
        """Ensure the address type is static."""
        correct_address_type = "static"
        assert v.lower() == correct_address_type, (
            f"address_type must be '{correct_address_type}'"
        )
        return v

    @field_validator("scope")
    def validate_scope(cls, v: str | None) -> str | None:
        """Validate the scope is global, link, or host."""
        if v:
            v = v.lower()
        assert v in (
            "global",
            "link",
            "host",
        ), "scope must be one of 'global', 'link', or 'host'"
        return v


class InetManualNetworkAddress(InetNetworkAddress):
    """Manually configured network address."""

    address_type: str = "manual"
    hwaddress: str | None = Field(examples=["12:34:56:78:9A:BC"], default=None)
    mtu: int | None = Field(examples=["1500"], default=None)

    @field_validator("address_type")
    def validate_own_address_type(cls, v: str) -> str:
        """Ensure the address type is manual."""
        correct_address_type = "manual"
        assert v.lower() == correct_address_type, (
            f"address_type must be '{correct_address_type}'"
        )
        return v


class InetDhcpNetworkAddress(InetNetworkAddress):
    """DHCP network address."""

    address_type: str = "dhcp"
    hostname: str | None = Field(examples=["wlanpi"], default=None)
    metric: int | None = Field(examples=["10"], default=None)
    leasetime: int | None = Field(examples=["3600"], default=None)
    vendor: str | None = Field(default=None)
    client: str | None = Field(default=None)
    hwaddress: str | None = Field(examples=["12:34:56:78:9A:BC"], default=None)

    @field_validator("address_type")
    def validate_own_address_type(cls, v: str) -> str:
        """Ensure the address type is dhcp."""
        correct_address_type = "dhcp"
        assert v.lower() == correct_address_type, (
            f"address_type must be '{correct_address_type}'"
        )
        return v


class Vlan(BaseModel):
    """A VLAN definition on an interface."""

    interface: str = Field(examples=["eth0"])
    vlan_tag: int = Field(examples=[20])
    if_control: str = Field(examples=["auto"])
    # addresses: list[InetNetworkAddress] = Field()
    # addresses: list[Union[InetStaticNetworkAddress, InetDhcpNetworkAddress, InetManualNetworkAddress, InetLoopbackNetworkAddress] ] = Field()
    addresses: list[
        InetStaticNetworkAddress
        | InetDhcpNetworkAddress
        | InetManualNetworkAddress
        | InetLoopbackNetworkAddress
    ] = Field()


class NetworkConfigResponse(BaseModel):
    """Result of a network configuration operation."""

    success: bool = True
    result: typing.Any = Field(default=None)
    errors: dict[str, Any] | None = None


NETWORK_ADDRESS_TYPES = {
    "inet": {
        "base": InetNetworkAddress,
        "loopback": InetLoopbackNetworkAddress,
        "static": InetStaticNetworkAddress,
        "manual": InetManualNetworkAddress,
        "dhcp": InetDhcpNetworkAddress,
    }
}
