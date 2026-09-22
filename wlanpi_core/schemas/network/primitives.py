"""Schemas for network primitive outputs."""

from typing import Any

from pydantic import BaseModel, Field


class RoutingTable(BaseModel):
    """Routing table for a namespace."""

    namespace: str | None = None
    routes: list[dict[str, Any]] = Field(default_factory=list)


class LinkStats(BaseModel):
    """Per-interface link statistics."""

    interface: str
    namespace: str | None = None
    link_detected: str | None = None
    speed_mbps: int | None = None
    duplex: str | None = None
    port: str | None = None
    driver: str | None = None
    raw: dict[str, str] = Field(default_factory=dict)


class SocketConnection(BaseModel):
    """One socket connection."""

    protocol: str
    state: str
    recv_q: Any = None
    send_q: Any = None
    local: str
    peer: str


class ConnectionsResponse(BaseModel):
    """Socket connections for a namespace."""

    namespace: str | None = None
    connections: list[SocketConnection] = Field(default_factory=list)


class DhcpRenewResponse(BaseModel):
    """Result of renewing a DHCP lease."""

    interface: str
    namespace: str | None = None
    status: str


class DhcpLeasesResponse(BaseModel):
    """Parsed DHCP leases."""

    leases: list[dict[str, Any]] = Field(default_factory=list)
    source: str
    error: str | None = None


class WlanAdapterDriver(BaseModel):
    """A WLAN interface and its bound driver."""

    interface: str = Field(description="Linux interface name from iw dev, e.g. wlan0")
    driver: str | None = Field(
        default=None,
        description="Kernel driver from ethtool -i, e.g. iwlwifi, ath9k_htc",
    )
    bus: str = Field(
        description="Attachment bus for this interface: usb, pci, or platform (SDIO/on-board)",
    )


class WlanUsbDriversResponse(BaseModel):
    """USB-attached WLAN adapters and their drivers."""

    adapters: list[WlanAdapterDriver] = Field(
        default_factory=list,
        description=(
            "USB-attached WLAN interfaces only. "
            "Empty array is normal on devices with only PCI/on-board Wi-Fi — use "
            "GET /network/wlan/pci-drivers instead."
        ),
    )
    interfaces_scanned: int = Field(
        default=0,
        description="Wireless interfaces enumerated via iw dev before USB filtering",
    )


class PciDevice(BaseModel):
    """A PCI device from lspci."""

    pci_id: str = Field(description="lspci BDF prefix, e.g. 0000:01:00.0")
    description: str = Field(description="Human-readable lspci device line")


class WlanPciDriversResponse(BaseModel):
    """PCI or platform WLAN adapters and their drivers."""

    adapters: list[WlanAdapterDriver] = Field(
        default_factory=list,
        description=(
            "WLAN interfaces on PCI or platform/SDIO buses. "
            "Multiple entries can share one PHY (e.g. wlan0 + wlanpi0)."
        ),
    )
    pci_devices: list[PciDevice] = Field(
        default_factory=list,
        description="Wireless PCI functions from lspci (may be non-empty when adapters is empty)",
    )
    interfaces_scanned: int = Field(
        default=0,
        description="Wireless interfaces enumerated via iw dev before bus filtering",
    )


class WlanLink(BaseModel):
    """Wireless association state for one interface (from ``iw link``)."""

    interface: str
    namespace: str | None = None
    connected: bool = Field(description="Whether the interface is associated")
    ssid: str | None = Field(default=None, json_schema_extra={"example": "HomeNet"})
    bssid: str | None = Field(
        default=None, json_schema_extra={"example": "68:51:34:7c:32:13"}
    )
    freq_mhz: float | None = Field(default=None, json_schema_extra={"example": 5200.0})
    signal_dbm: float | None = Field(default=None, json_schema_extra={"example": -48.0})
    rx_bitrate: str | None = Field(
        default=None, json_schema_extra={"example": "286.7 MBit/s HE-MCS 11"}
    )
    tx_bitrate: str | None = Field(
        default=None, json_schema_extra={"example": "286.7 MBit/s HE-MCS 11"}
    )
    rx_bytes: int | None = Field(default=None, json_schema_extra={"example": 2112666})
    tx_bytes: int | None = Field(default=None, json_schema_extra={"example": 104496501})
    raw: str | None = Field(
        default=None,
        description="Raw iw link output for diagnostics; do not parse",
    )
