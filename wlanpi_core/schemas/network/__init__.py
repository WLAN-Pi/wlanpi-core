"""Network schemas."""

from .network import (
    APIConfig,
    ConnectedNetwork,
    Interface,
    Interfaces,
    NetConfig,
    NetworkEvent,
    NetworkSetupLog,
    NetworkSetupStatus,
    PublicIP,
    RevertNamespace,
    ScanItem,
    ScanResults,
    WlanInterfaceSetup,
    WlanRevertRequest,
)
from .primitives import (
    ConnectionsResponse,
    DhcpLeasesResponse,
    DhcpRenewResponse,
    LinkStats,
    RoutingTable,
    WlanLink,
    WlanPciDriversResponse,
    WlanUsbDriversResponse,
)
