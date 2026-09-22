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
from wlanpi_core.wpa.scan import (
    fetch_scan_results,
    find_bss,
    parse_iw_scan_output,
    parse_key_mgmt,
    parse_wpa_scan_results,
    run_interface_scan,
    run_iw_scan,
)
from wlanpi_core.wpa.status import get_wpa_status
from wlanpi_core.wpa.supplicant import (
    kill_all_supplicants,
    parse_wpa_log,
    start_or_restart_supplicant,
)

__all__ = [
    "fetch_scan_results",
    "find_bss",
    "generate_global_header",
    "generate_network_block",
    "get_wpa_status",
    "kill_all_supplicants",
    "parse_iw_scan_output",
    "parse_key_mgmt",
    "parse_wpa_log",
    "parse_wpa_scan_results",
    "run_interface_scan",
    "run_iw_scan",
    "start_or_restart_supplicant",
    "write_wpa_config",
]
