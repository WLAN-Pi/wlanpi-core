"""
Adapter and interface management for network adapters.

This package provides focused modules for PHY operations, interface management,
and interface discovery, separate from namespace concerns.
"""

from wlanpi_core.adapters.discovery import (
    get_interface_by_name,
    list_interfaces,
)
from wlanpi_core.adapters.interface import (
    bring_interface_down,
    bring_interface_up,
    create_interface,
    delete_interface,
    get_interface_info,
)
from wlanpi_core.adapters.phy import (
    get_phy_info,
    list_phys,
    move_phy_to_namespace,
    move_phy_to_root,
)

__all__ = [
    # PHY operations
    "list_phys",
    "get_phy_info",
    "move_phy_to_namespace",
    "move_phy_to_root",
    # Interface operations
    "create_interface",
    "delete_interface",
    "get_interface_info",
    "bring_interface_up",
    "bring_interface_down",
    # Discovery
    "list_interfaces",
    "get_interface_by_name",
]
