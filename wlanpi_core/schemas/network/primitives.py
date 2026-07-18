from typing import Any, Optional

from pydantic import BaseModel, Field


class RoutingTable(BaseModel):
    namespace: Optional[str] = None
    routes: list[dict[str, Any]] = Field(default_factory=list)


class LinkStats(BaseModel):
    interface: str
    namespace: Optional[str] = None
    link_detected: Optional[str] = None
    speed_mbps: Optional[int] = None
    duplex: Optional[str] = None
    port: Optional[str] = None
    driver: Optional[str] = None
    raw: dict[str, str] = Field(default_factory=dict)


class SocketConnection(BaseModel):
    protocol: str
    state: str
    recv_q: Any = None
    send_q: Any = None
    local: str
    peer: str


class ConnectionsResponse(BaseModel):
    namespace: Optional[str] = None
    connections: list[SocketConnection] = Field(default_factory=list)


class DhcpRenewResponse(BaseModel):
    interface: str
    namespace: Optional[str] = None
    status: str


class DhcpLeasesResponse(BaseModel):
    leases: list[dict[str, Any]] = Field(default_factory=list)
    source: str
    error: Optional[str] = None


class WlanAdapterDriver(BaseModel):
    interface: str = Field(description="Linux interface name from iw dev, e.g. wlan0")
    driver: Optional[str] = Field(
        default=None,
        description="Kernel driver from ethtool -i, e.g. iwlwifi, ath9k_htc",
    )
    bus: str = Field(
        description="Attachment bus for this interface: usb, pci, or platform (SDIO/on-board)",
    )


class WlanUsbDriversResponse(BaseModel):
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
    pci_id: str = Field(description="lspci BDF prefix, e.g. 0000:01:00.0")
    description: str = Field(description="Human-readable lspci device line")


class WlanPciDriversResponse(BaseModel):
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
