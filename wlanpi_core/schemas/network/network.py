from enum import Enum
from typing import Any, List, Optional, Union

from pydantic import BaseModel, Extra, Field, field_validator, model_validator

from wlanpi_core.utils.validation import (
    validate_config_id,
    validate_interface_name,
    validate_namespace_name,
    validate_phy_name,
    validate_ssid,
    validate_wpa_text,
)


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
            # Placeholders for DHCP requests; parsed `ip -j addr` output also
            # sets dynamic=true and must keep its real address (issue #147)
            if self.prefixlen is None:
                self.prefixlen = 24
            if self.local is None:
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
    
class SecurityTypes(str, Enum):
    wpa2 = "WPA2-PSK"
    wpa3 = "WPA3-PSK"
    open = "OPEN"
    owe = "OWE"


_REDACTED = "***"
_SENSITIVE_SECURITY_FIELDS = (
    "psk",
    "password",
    "private_key",
    "client_cert",
    "ca_cert",
)


def _redact_security_dict(security: Optional[dict]) -> Optional[dict]:
    """Return a copy of a security dict with credential fields masked."""
    if not security:
        return security
    redacted = dict(security)
    for field in _SENSITIVE_SECURITY_FIELDS:
        if redacted.get(field):
            redacted[field] = _REDACTED
    return redacted


def _redact_root_config_dict(data: dict) -> dict:
    redacted = dict(data)
    redacted["security"] = _redact_security_dict(redacted.get("security"))
    return redacted


class NetSecurity(BaseModel):
    ssid: str
    security: SecurityTypes
    psk: Optional[str] = None
    sae_pwe: Optional[int] = None
    pmf: Optional[int] = None
    identity: Optional[str] = None
    password: Optional[str] = None
    client_cert: Optional[str] = None
    private_key: Optional[str] = None
    ca_cert: Optional[str] = None

    @field_validator("ssid")
    @classmethod
    def validate_ssid_field(cls, value: str) -> str:
        return validate_ssid(value)

    @field_validator(
        "psk",
        "identity",
        "password",
        "client_cert",
        "private_key",
        "ca_cert",
    )
    @classmethod
    def validate_wpa_text_field(cls, value: Optional[str], info) -> Optional[str]:
        if value is None:
            return None
        return validate_wpa_text(value, info.field_name)

    def __str__(self) -> str:
        return str(_redact_security_dict(self.model_dump()))

    __repr__ = __str__


class RootConfig(BaseModel):
    mode: NetworkModeEnum = NetworkModeEnum.managed
    iface_display_name: str
    phy: str
    interface: str
    security: Optional[NetSecurity] = None
    mlo: bool = False
    default_route: bool = False
    autostart_app: Optional[str] = None

    @field_validator("interface", "iface_display_name")
    @classmethod
    def validate_interface_fields(cls, value: str) -> str:
        return validate_interface_name(value)

    @field_validator("phy")
    @classmethod
    def validate_phy_field(cls, value: str) -> str:
        return validate_phy_name(value)

    def __str__(self) -> str:
        return str(_redact_root_config_dict(self.model_dump()))

    __repr__ = __str__


class NamespaceConfig(RootConfig):
    namespace: str

    @field_validator("namespace")
    @classmethod
    def validate_namespace_field(cls, value: str) -> str:
        return validate_namespace_name(value)


class NetConfig(BaseModel):
    id: str
    namespaces: Optional[list[NamespaceConfig]] = None
    roots: Optional[list[RootConfig]] = None

    @field_validator("id")
    @classmethod
    def validate_id_field(cls, value: str) -> str:
        return validate_config_id(value)

    def __str__(self) -> str:
        data = self.model_dump()
        if data.get("namespaces"):
            data["namespaces"] = [
                _redact_root_config_dict(entry) for entry in data["namespaces"]
            ]
        if data.get("roots"):
            data["roots"] = [_redact_root_config_dict(entry) for entry in data["roots"]]
        return str(data)

    __repr__ = __str__


class NetConfigUpdate(BaseModel):
    namespaces: Optional[list[NamespaceConfig]] = None
    roots: Optional[list[RootConfig]] = None


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

    @field_validator("interface")
    @classmethod
    def validate_interface_field(cls, value: str) -> str:
        return validate_interface_name(value)


class WlanRevertRequest(BaseModel):
    iface: str = Field(example="wlan0")
    namespace: str
    delete_namespace: bool = True

    @field_validator("iface")
    @classmethod
    def validate_iface_field(cls, value: str) -> str:
        return validate_interface_name(value)

    @field_validator("namespace")
    @classmethod
    def validate_revert_namespace_field(cls, value: str) -> str:
        return validate_namespace_name(value)


class NetworkEvent(BaseModel):
    event: str = Field(example="authenticated")
    time: str = Field(example="2024-09-01 03:52:31.232828")


class NetworkSetupLog(BaseModel):
    selectErr: str = Field(example="fi.w1.wpa_supplicant1.NetworkUnknown")
    eventLog: List[NetworkEvent]


class NetworkSetupStatus(BaseModel):
    status: str = Field(example="connected")
    response: NetworkSetupLog
    connectedNet: Optional[ScanItem]
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
