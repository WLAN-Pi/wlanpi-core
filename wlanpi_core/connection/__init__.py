"""
Connection monitoring for network interfaces.

This package provides functions for monitoring network connection status
and managing connection lifecycle.
"""

from wlanpi_core.connection.monitor import (
    ConnectionMonitor,
    stop_all_connection_monitors,
    stop_connection_monitor,
)

__all__ = [
    "ConnectionMonitor",
    "stop_connection_monitor",
    "stop_all_connection_monitors",
]
