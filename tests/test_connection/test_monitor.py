"""
Tests for connection monitoring.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock

from wlanpi_core.connection.monitor import (
    ConnectionMonitor,
    stop_all_connection_monitors,
    stop_connection_monitor,
)


class TestConnectionMonitor:
    """Tests for ConnectionMonitor class."""

    @patch("wlanpi_core.connection.monitor.get_wpa_status")
    @patch("wlanpi_core.connection.monitor.restart_dhcp_with_timeout")
    @patch("wlanpi_core.connection.monitor.set_default_route")
    @patch("wlanpi_core.namespaces.apps.start_app_in_namespace")
    def test_start_monitor_connection_completes(
        self,
        mock_start_app,
        mock_set_route,
        mock_dhcp,
        mock_get_status,
    ):
        """Test monitor when connection completes."""
        from wlanpi_core.schemas.network.network import NamespaceConfig, NetworkModeEnum, NetSecurity, SecurityTypes

        config = NamespaceConfig(
            namespace="test_ns",
            interface="wlan0",
            phy="phy0",
            iface_display_name="wlan0",
            mode=NetworkModeEnum.managed,
            security=NetSecurity(ssid="test", security=SecurityTypes.wpa2, psk="pass"),
            default_route=True,
            autostart_app="my_app",
        )

        # Mock status progression
        mock_get_status.side_effect = [
            {"wpa_status": {"wpa_state": "SCANNING"}},
            {"wpa_status": {"wpa_state": "ASSOCIATING"}},
            {"wpa_status": {"wpa_state": "COMPLETED"}},
        ]

        # Start monitor (will run in background thread)
        ConnectionMonitor.start_monitor(config, "wlan0", "test_ns", timeout=5)

        # Give thread a moment to start
        import time
        time.sleep(0.1)

        # Stop monitor
        stop_connection_monitor("test_ns", "wlan0")

    @patch("wlanpi_core.connection.monitor.get_wpa_status")
    def test_start_monitor_timeout(self, mock_get_status):
        """Test monitor when connection times out."""
        from wlanpi_core.schemas.network.network import NamespaceConfig, NetworkModeEnum, NetSecurity, SecurityTypes

        config = NamespaceConfig(
            namespace="test_ns",
            interface="wlan0",
            phy="phy0",
            iface_display_name="wlan0",
            mode=NetworkModeEnum.managed,
            security=NetSecurity(ssid="test", security=SecurityTypes.wpa2, psk="pass"),
        )

        # Mock status never completing
        mock_get_status.return_value = {"wpa_status": {"wpa_state": "SCANNING"}}

        ConnectionMonitor.start_monitor(config, "wlan0", "test_ns", timeout=1)

        import time
        time.sleep(1.5)  # Wait for timeout

        stop_connection_monitor("test_ns", "wlan0")


class TestStopConnectionMonitor:
    """Tests for stop_connection_monitor function."""

    def test_stop_connection_monitor(self):
        """Test stopping a connection monitor."""
        # Should handle gracefully even if no monitor exists
        stop_connection_monitor("test_ns", "wlan0")

    def test_stop_connection_monitor_root(self):
        """Test stopping monitor in root namespace."""
        stop_connection_monitor(None, "wlan0")


class TestStopAllConnectionMonitors:
    """Tests for stop_all_connection_monitors function."""

    def test_stop_all_connection_monitors(self):
        """Test stopping all connection monitors."""
        # Should handle gracefully even if no monitors exist
        stop_all_connection_monitors()
