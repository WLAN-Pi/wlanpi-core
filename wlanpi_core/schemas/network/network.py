"""Schemas for network configuration and primitives."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from wlanpi_core.utils.validation import (
    validate_config_id,
    validate_interface_name,
    validate_namespace_name,
    validate_phy_name,
    validate_ssid,
    validate_wpa_text,
)


class PublicIP(BaseModel):
    """Public IP address and geo information."""

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


class IPInterfaceAddress(BaseModel, extra="allow"):
    """One IP address assigned to an interface."""

    family: str = Field(examples=["inet", "inet6"])
    local: str | None = Field(examples=["10.0.0.1"], default=None)
    prefixlen: int | None = Field(examples=[24, 32, 128], default=None)
    broadcast: str | None = Field(examples=["10.0.0.255"], default=None)
    anycast: str | None = Field(examples=["10.0.0.255"], default=None)
    scope: str | int = Field(examples=["global", "link", "host", 3], default="global")
    dynamic: bool = Field(examples=[False, True], default=False)
    label: str | None = Field(examples=["eth0", "lo"], default=None)
    valid_life_time: int | None = Field(examples=[3600, None], default=None)
    preferred_life_time: int | None = Field(examples=[3600, 41213, None], default=None)

    @model_validator(mode="after")
    def check_dynamic_condition(self) -> Any:
        """Fill DHCP placeholder values for dynamic addresses."""
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


class IPInterface(BaseModel, extra="allow"):
    """One network interface and its addresses."""

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


class NetworkModeEnum(StrEnum):
    """Operating modes for a root interface."""

    managed = "managed"
    monitor = "monitor"


class SecurityTypes(StrEnum):
    """Supported WLAN security types."""

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


def _redact_security_dict(
    security: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a copy of a security dict with credential fields masked."""
    if not security:
        return security
    redacted = dict(security)
    for field in _SENSITIVE_SECURITY_FIELDS:
        if redacted.get(field):
            redacted[field] = _REDACTED
    return redacted


def _redact_root_config_dict(data: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(data)
    redacted["security"] = _redact_security_dict(redacted.get("security"))
    return redacted


class NetSecurity(BaseModel):
    """WLAN security settings for a connection."""

    ssid: str
    security: SecurityTypes
    psk: str | None = None
    sae_pwe: int | None = None
    pmf: int | None = None
    identity: str | None = None
    password: str | None = None
    client_cert: str | None = None
    private_key: str | None = None
    ca_cert: str | None = None

    @field_validator("ssid")
    @classmethod
    def validate_ssid_field(cls, value: str) -> str:
        """Validate the SSID value."""
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
    def validate_wpa_text_field(cls, value: str | None, info: Any) -> str | None:
        """Validate a WPA text field such as psk or password."""
        if value is None:
            return None
        return validate_wpa_text(value, info.field_name)

    @model_validator(mode="after")
    def validate_psk_format(self) -> "NetSecurity":
        """Reject PSKs that wpa_supplicant would refuse at start (#278).

        WPA2: an 8-63 character printable-ASCII passphrase, or 64 hex digits.
        WPA3 (SAE): a passphrase only; SAE cannot use a raw hex PSK.
        """
        if self.psk is None or self.security not in (
            SecurityTypes.wpa2,
            SecurityTypes.wpa3,
        ):
            return self
        is_hex_key = len(self.psk) == 64 and all(
            c in "0123456789abcdefABCDEF" for c in self.psk
        )
        if is_hex_key and self.security == SecurityTypes.wpa2:
            return self
        if not 8 <= len(self.psk) <= 63 or not all(
            32 <= ord(c) <= 126 for c in self.psk
        ):
            raise ValueError(
                "psk must be 8-63 printable ASCII characters"
                + (" or 64 hex digits" if self.security == SecurityTypes.wpa2 else "")
            )
        return self

    def __str__(self) -> str:
        """Return the redacted security dict as a string."""
        return str(_redact_security_dict(self.model_dump()))

    __repr__ = __str__


class RootConfig(BaseModel):
    """Configuration for a root (non-namespaced) interface."""

    mode: NetworkModeEnum = NetworkModeEnum.managed
    iface_display_name: str
    phy: str
    interface: str
    security: NetSecurity | None = None
    default_route: bool = False
    autostart_app: str | None = None

    @field_validator("interface", "iface_display_name")
    @classmethod
    def validate_interface_fields(cls, value: str) -> str:
        """Validate interface field names."""
        return validate_interface_name(value)

    @field_validator("phy")
    @classmethod
    def validate_phy_field(cls, value: str) -> str:
        """Validate the PHY name."""
        return validate_phy_name(value)

    def __str__(self) -> str:
        """Return the redacted config as a string."""
        return str(_redact_root_config_dict(self.model_dump()))

    __repr__ = __str__


class NamespaceConfig(RootConfig):
    """Configuration for an interface in a network namespace."""

    namespace: str

    @field_validator("namespace")
    @classmethod
    def validate_namespace_field(cls, value: str) -> str:
        """Validate the namespace name."""
        return validate_namespace_name(value)


class NetConfig(BaseModel):
    """A named network configuration with root and namespace interfaces."""

    id: str
    namespaces: list[NamespaceConfig] | None = None
    roots: list[RootConfig] | None = None

    @field_validator("id")
    @classmethod
    def validate_id_field(cls, value: str) -> str:
        """Validate the configuration ID."""
        return validate_config_id(value)

    @model_validator(mode="after")
    def validate_unique_interfaces(self) -> "NetConfig":
        """Reject entries that would claim the same radio or the same name.

        Runtime state is keyed by (namespace, interface name), and each
        `interface` names one live radio, so two entries may not share an
        `interface`, reuse another entry's `interface` as a display name, or
        use the same display name in the same namespace.
        """
        entries: list[tuple[str | None, RootConfig]] = [
            (entry.namespace, entry) for entry in self.namespaces or []
        ]
        entries += [(None, entry) for entry in self.roots or []]
        interfaces = [entry.interface for _ns, entry in entries]
        duplicates = sorted({i for i in interfaces if interfaces.count(i) > 1})
        if duplicates:
            raise ValueError(f"interface used by more than one entry: {duplicates}")
        for _ns, entry in entries:
            display = entry.iface_display_name
            if display and display != entry.interface and display in interfaces:
                raise ValueError(
                    f"iface_display_name {display!r} is another entry's interface"
                )
        names = [
            (ns, entry.iface_display_name or entry.interface) for ns, entry in entries
        ]
        clashes = sorted(
            {f"{ns or 'root'}/{n}" for ns, n in names if names.count((ns, n)) > 1}
        )
        if clashes:
            raise ValueError(f"interface name used twice in one namespace: {clashes}")
        return self

    def __str__(self) -> str:
        """Return the config with credentials redacted."""
        data = self.model_dump()
        if data.get("namespaces"):
            data["namespaces"] = [
                _redact_root_config_dict(entry) for entry in data["namespaces"]
            ]
        if data.get("roots"):
            data["roots"] = [_redact_root_config_dict(entry) for entry in data["roots"]]
        return str(data)

    __repr__ = __str__


class NetSecurityPublic(BaseModel):
    """Security settings as the API returns them: secrets become flags."""

    ssid: str
    security: SecurityTypes
    psk_set: bool = False
    password_set: bool = False
    sae_pwe: int | None = None
    pmf: int | None = None
    identity: str | None = None
    client_cert: str | None = None
    private_key: str | None = None
    ca_cert: str | None = None

    @classmethod
    def from_security(cls, security: NetSecurity) -> "NetSecurityPublic":
        """Drop psk and password, recording only whether each is set."""
        return cls(
            **security.model_dump(exclude={"psk", "password"}),
            psk_set=bool(security.psk),
            password_set=bool(security.password),
        )


class RootConfigPublic(RootConfig):
    """A root entry as the API returns it (no secrets)."""

    # Narrower public type for the same field.
    security: NetSecurityPublic | None = None  # type: ignore[assignment]


class NamespaceConfigPublic(NamespaceConfig):
    """A namespace entry as the API returns it (no secrets)."""

    security: NetSecurityPublic | None = None  # type: ignore[assignment]


class NetConfigPublic(NetConfig):
    """A configuration as the API returns it: psk and password omitted.

    `psk_set` / `password_set` say whether a secret is stored. Send the
    entry back without `psk` or `password` in a PATCH to keep it.
    """

    namespaces: list[NamespaceConfigPublic] | None = None  # type: ignore[assignment]
    roots: list[RootConfigPublic] | None = None  # type: ignore[assignment]

    @classmethod
    def from_config(cls, cfg: NetConfig) -> "NetConfigPublic":
        """Build the public view of a stored configuration."""

        def public(entry: RootConfig) -> dict[str, Any]:
            data = entry.model_dump(exclude={"security"})
            data["security"] = (
                NetSecurityPublic.from_security(entry.security)
                if entry.security
                else None
            )
            return data

        return cls(
            id=cfg.id,
            namespaces=[public(e) for e in cfg.namespaces or []],  # type: ignore[misc]
            roots=[public(e) for e in cfg.roots or []],  # type: ignore[misc]
        )


class NetConfigUpdate(BaseModel):
    """Partial update for a network configuration."""

    namespaces: list[NamespaceConfig] | None = None
    roots: list[RootConfig] | None = None


class ScanItem(BaseModel):
    """One scanned network."""

    ssid: str = Field(json_schema_extra={"example": "A Network"})
    bssid: str = Field(json_schema_extra={"example": "11:22:33:44:55"})
    key_mgmt: str = Field(json_schema_extra={"example": "wpa-psk"})
    signal: int = Field(json_schema_extra={"example": -65})
    freq: int = Field(json_schema_extra={"example": 5650})
    minrate: int = Field(json_schema_extra={"example": 1000000})


class ScanResults(BaseModel):
    """List of scanned networks."""

    nets: list[ScanItem]


class WlanInterfaceSetup(BaseModel):
    """Legacy WLAN interface setup request."""

    interface: str = Field(json_schema_extra={"example": "wlan0"})
    netConfig: NetConfig
    removeAllFirst: bool

    @field_validator("interface")
    @classmethod
    def validate_interface_field(cls, value: str) -> str:
        """Validate the interface name."""
        return validate_interface_name(value)


class WlanRevertRequest(BaseModel):
    """Request to revert an interface to the root namespace."""

    iface: str = Field(json_schema_extra={"example": "wlan0"})
    namespace: str
    delete_namespace: bool = True

    @field_validator("iface")
    @classmethod
    def validate_iface_field(cls, value: str) -> str:
        """Validate the interface name."""
        return validate_interface_name(value)

    @field_validator("namespace")
    @classmethod
    def validate_revert_namespace_field(cls, value: str) -> str:
        """Validate the namespace name."""
        return validate_namespace_name(value)


class NetworkEvent(BaseModel):
    """One event in a network setup log."""

    event: str = Field(json_schema_extra={"example": "authenticated"})
    time: str = Field(json_schema_extra={"example": "2024-09-01 03:52:31.232828"})


class AdapterOutcome(BaseModel):
    """What happened to one configuration entry during activation."""

    interface: str
    namespace: str | None = None
    status: str = Field(
        description=(
            "connected, provisioned or error; skipped for a default entry whose "
            "radio Core did not create; in_use for a radio another tool is using "
            "(left alone, the rest of the configuration still runs)"
        )
    )
    detail: str = ""
    invalid: bool = Field(
        default=False, description="The entry failed configuration validation"
    )


class ActivationResponse(BaseModel):
    """Result of activating a configuration, with one outcome per entry."""

    id: str
    message: str
    outcomes: list[AdapterOutcome] = []


class NetworkSetupLog(BaseModel):
    """Log of events during network setup."""

    selectErr: str = Field(
        json_schema_extra={"example": "fi.w1.wpa_supplicant1.NetworkUnknown"}
    )
    eventLog: list[NetworkEvent]


class NetworkSetupStatus(BaseModel):
    """Result of a network setup operation."""

    status: str = Field(json_schema_extra={"example": "connected"})
    response: NetworkSetupLog
    connectedNet: ScanItem | None
    input: str


class ConnectedNetwork(BaseModel):
    """Whether the device is connected and to which network."""

    connectedStatus: bool = Field(json_schema_extra={"example": True})
    connectedNet: ScanItem | None


class LeftAlone(BaseModel):
    """A namespace holding radios that Core did not clean up, and why."""

    namespace: str
    interfaces: list[str] = []
    phys: list[str] = []
    core_created: bool = False
    reason: str


class LeftoversResponse(BaseModel):
    """Namespaces Core left alone; clear them with POST /network/config/reset."""

    left_alone: list[LeftAlone] = []


class DeactivationResponse(BaseModel):
    """Result of deactivating a configuration."""

    id: str
    message: str
    left_alone: list[LeftAlone] = []


class NamespaceResetRequest(BaseModel):
    """Namespaces to return to root, named explicitly by the caller."""

    namespaces: list[str] = Field(min_length=1)

    @field_validator("namespaces")
    @classmethod
    def validate_namespaces(cls, value: list[str]) -> list[str]:
        """Validate each namespace name."""
        return [validate_namespace_name(name) for name in value]


class NamespaceResetResult(BaseModel):
    """What resetting one namespace did."""

    namespace: str
    phys_returned: list[str] = []
    deleted: bool = False
    remaining: list[str] = []
    detail: str = ""


class NamespaceResetResponse(BaseModel):
    """Per-namespace results of a reset."""

    results: list[NamespaceResetResult]


class RevertNamespace(BaseModel):
    """Result of reverting a namespace."""

    success: bool = Field(json_schema_extra={"example": True})
    message: str
    left_alone: list[LeftAlone] = []


class Interface(BaseModel):
    """One interface name."""

    interface: str = Field(json_schema_extra={"example": "wlan0"})


class Interfaces(BaseModel):
    """List of interface names."""

    interfaces: list[Interface]


class APIConfig(BaseModel):
    """Legacy API configuration."""

    timeout: int = Field(json_schema_extra={"example": 20})
