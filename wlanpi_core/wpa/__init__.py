"""
WPA supplicant management.

This package provides functions for managing wpa_supplicant configuration,
process lifecycle, and status checking.
"""

from wlanpi_core.wpa.config import (
    generate_global_header,
    generate_network_block,
    write_wpa_config,
)
from wlanpi_core.wpa.supplicant import (
    kill_all_supplicants,
    parse_wpa_log,
    start_or_restart_supplicant,
)
from wlanpi_core.wpa.status import (
    get_wpa_status,
    parse_key_mgmt,
)

__all__ = [
    # Config management
    "write_wpa_config",
    "generate_network_block",
    "generate_global_header",
    # Supplicant management
    "start_or_restart_supplicant",
    "parse_wpa_log",
    "kill_all_supplicants",
    # Status
    "get_wpa_status",
    "parse_key_mgmt",
]
