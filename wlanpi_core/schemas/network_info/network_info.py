from pydantic import BaseModel, Field


class NetworkInfo(BaseModel):
    interfaces: dict = Field()
    wlan_interfaces: dict = Field()
    eth0_ipconfig_info: dict = Field()
    vlan_info: dict = Field()
    lldp_neighbour_info: dict = Field()
    cdp_neighbour_info: dict = Field()
    public_ip: dict = Field()
