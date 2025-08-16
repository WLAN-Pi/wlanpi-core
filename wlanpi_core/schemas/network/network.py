from typing import Any, List, Optional, Union
from enum import Enum
from pydantic import BaseModel, Extra, Field, model_validator


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
    local: Optional[str] = Field(examples=["10.0.0.1"], default=None)
    prefixlen: Optional[int] = Field(examples=[24, 32, 128], default=None)
    broadcast: Optional[str] = Field(examples=["10.0.0.255"], default=None)
    anycast: Optional[str] = Field(examples=["10.0.0.255"], default=None)
    scope: Union[str, int] = Field(
        examples=["global", "link", "host", 3], default="global"
    )
    dynamic: bool = Field(examples=[False, True], default=False)
    label: Optional[str] = Field(examples=["eth0", "lo"], default=None)
    valid_life_time: Optional[int] = Field(examples=[3600, None], default=None)
    preferred_life_time: Optional[int] = Field(
        examples=[3600, 41213, None], default=None
    )

    @model_validator(mode="after")
    def check_dynamic_condition(self) -> Any:
        # print(self)
        if self.dynamic:
            self.prefixlen = 24
            self.local = "0.0.0.0"
        else:
            if self.prefixlen is None:
                raise ValueError("prefixlen required unless dynamic is True")
            if self.local is None:
                raise ValueError("local required unless dynamic is True")
        return self


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

class NetworkModeEnum(str, Enum):
    managed = "managed"
    monitor = "monitor"
    
class NetSecurity(BaseModel):
    ssid: str
    security: str
    psk: Optional[str] = None
    identity: Optional[str] = None
    password: Optional[str] = None
    client_cert: Optional[str] = None
    private_key: Optional[str] = None
    ca_cert: Optional[str] = None
    
class NetSecurityUpdate(BaseModel):
    ssid: Optional[str] = None
    security: Optional[str] = None
    psk: Optional[str] = None
    identity: Optional[str] = None
    password: Optional[str] = None
    client_cert: Optional[str] = None
    private_key: Optional[str] = None
    ca_cert: Optional[str] = None
    

class RootConfig(BaseModel):
    mode: NetworkModeEnum = NetworkModeEnum.managed
    iface_display_name: str
    phy: str
    interface: str
    security: NetSecurity
    mlo: bool = False
    default_route: bool = False
    autostart_app: Optional[str] = None
    
    
class NamespaceConfig(RootConfig):
    namespace: str
    
class NetConfig(BaseModel):
    id: str
    namespaces: list[NamespaceConfig]
    roots: list[RootConfig]
    active: bool = False
    
class NetConfigCreate(BaseModel):
    id: str
    namespace: str
    use_namespace: bool = False
    mode: NetworkModeEnum = NetworkModeEnum.managed
    iface_display_name: str
    phy: str = "phy0"
    interface: str = "wlan0"
    security: NetSecurity
    mlo: Optional[bool] = False
    default_route: bool = False
    autostart_app: Optional[str] = None
    
class NetConfigUpdate(BaseModel):
    namespace: Optional[str] = None
    use_namespace: Optional[bool] = None
    mode: Optional[NetworkModeEnum] = None
    iface_display_name: Optional[str] = None
    phy: Optional[str] = None
    interface: Optional[str] = None
    security: Optional[NetSecurityUpdate] = None
    mlo: Optional[bool] = None
    default_route: Optional[bool] = None
    autostart_app: Optional[str] = None


class ScanItem(BaseModel):
    ssid: str = Field(example="A Network")
    bssid: str = Field(example="11:22:33:44:55")
    key_mgmt: str = Field(example="wpa-psk")
    signal: int = Field(example=-65)
    freq: int = Field(example=5650)
    minrate: int = Field(example=1000000)


class ScanResults(BaseModel):
    nets: List[ScanItem]


class WlanInterfaceSetup(BaseModel):
    interface: str = Field(example="wlan0")
    netConfig: NetConfig
    removeAllFirst: bool

class WlanRevertRequest(BaseModel):
    iface: str= Field(example="wlan0")
    namespace: str
    delete_namespace: bool = True

class NetworkEvent(BaseModel):
    event: str = Field(example="authenticated")
    time: str = Field(example="2024-09-01 03:52:31.232828")


class NetworkSetupLog(BaseModel):
    selectErr: str = Field(example="fi.w1.wpa_supplicant1.NetworkUnknown")
    eventLog: List[NetworkEvent]


class NetworkSetupStatus(BaseModel):
    status: str = Field(example="connected")
    response: NetworkSetupLog
    connectedNet: ScanItem
    input: str


class ConnectedNetwork(BaseModel):
    connectedStatus: bool = Field(example=True)
    connectedNet: Union[ScanItem, None]

class RevertNamespace(BaseModel):
    success: bool = Field(example=True)
    message: str


class Interface(BaseModel):
    interface: str = Field(example="wlan0")


class Interfaces(BaseModel):
    interfaces: List[Interface]


class APIConfig(BaseModel):
    timeout: int = Field(example=20)
