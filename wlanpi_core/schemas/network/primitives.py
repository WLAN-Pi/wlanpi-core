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
    interface: str
    driver: Optional[str] = None
    bus: str


class WlanUsbDriversResponse(BaseModel):
    adapters: list[WlanAdapterDriver] = Field(default_factory=list)


class PciDevice(BaseModel):
    pci_id: str
    description: str


class WlanPciDriversResponse(BaseModel):
    adapters: list[WlanAdapterDriver] = Field(default_factory=list)
    pci_devices: list[PciDevice] = Field(default_factory=list)
