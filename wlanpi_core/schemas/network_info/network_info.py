from typing import Optional

from pydantic import BaseModel, Field


class PublicIpInfo(BaseModel):
    info: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class NetworkInfo(BaseModel):
    interfaces: dict = Field()
    wlan_interfaces: dict = Field()
    eth0_ipconfig_info: dict = Field()
    vlan_info: dict = Field()
    lldp_neighbour_info: dict = Field()
    cdp_neighbour_info: dict = Field()
    public_ip: dict = Field()
