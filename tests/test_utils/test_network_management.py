"""
Tests for network management utilities (DHCP and routing).
"""
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.network_management import (
    restart_dhcp_with_timeout,
    set_default_route,
    write_dhcp_config,
)


class TestWriteDhcpConfig:
    """Tests for write_dhcp_config function."""

    def test_write_dhcp_config_success(self, tmp_path):
        """Test successful DHCP config writing."""
        write_dhcp_config("wlan0", tmp_path)

        assert (tmp_path / "wlan0.cfg").exists()
        content = (tmp_path / "wlan0.cfg").read_text()
        assert "allow-hotplug wlan0" in content
        assert "iface wlan0 inet dhcp" in content


class TestRestartDhcpWithTimeout:
    """Tests for restart_dhcp_with_timeout function."""

    @patch("wlanpi_core.utils.network_management.ns_exec")
    @patch("wlanpi_core.utils.network_management.time.sleep")
    def test_restart_dhcp_success(self, mock_sleep, mock_ns_exec):
        """Test successful DHCP restart."""
        mock_ns_exec.return_value = Mock()

        restart_dhcp_with_timeout("wlan0", "test_ns", timeout=15)

        # Should call ns_exec multiple times (cleanup + start)
        assert mock_ns_exec.call_count >= 2

    @patch("wlanpi_core.utils.network_management.ns_exec")
    @patch("wlanpi_core.utils.network_management.time.sleep")
    def test_restart_dhcp_timeout(self, mock_sleep, mock_ns_exec):
        """Test DHCP restart with timeout."""
        # First calls succeed, last one times out
        mock_ns_exec.side_effect = [
            Mock(),  # dhclient -r
            Mock(),  # pkill
            RunCommandError("timeout", 124),  # dhclient timeout
        ]

        # Should handle timeout gracefully
        restart_dhcp_with_timeout("wlan0", "test_ns", timeout=15)

    @patch("wlanpi_core.utils.network_management.ns_exec")
    @patch("wlanpi_core.utils.network_management.time.sleep")
    def test_restart_dhcp_handles_errors(self, mock_sleep, mock_ns_exec):
        """Test DHCP restart handles cleanup errors."""
        # Cleanup fails but should continue
        mock_ns_exec.side_effect = [
            RunCommandError("No process", 1),  # dhclient -r fails
            Mock(),  # pkill succeeds
            Mock(),  # dhclient start succeeds
        ]

        # Should not raise
        restart_dhcp_with_timeout("wlan0", "test_ns", timeout=15)


class TestSetDefaultRoute:
    """Tests for set_default_route function."""

    @patch("wlanpi_core.utils.network_management.ns_exec")
    def test_set_default_route_success(self, mock_ns_exec):
        """Test successful default route setting."""
        # Mock route show (no default route)
        mock_ns_exec.side_effect = [
            Mock(stdout=""),  # No default route
            Mock(),  # Route set succeeds
        ]

        set_default_route("wlan0", "test_ns")

        assert mock_ns_exec.call_count == 2

    @patch("wlanpi_core.utils.network_management.ns_exec")
    def test_set_default_route_already_set(self, mock_ns_exec):
        """Test default route when already set."""
        # Mock route show (default route exists)
        mock_ns_exec.return_value = Mock(stdout="default via 192.168.1.1 dev wlan0")

        set_default_route("wlan0", "test_ns")

        # Should only check, not set
        assert mock_ns_exec.call_count == 1

    @patch("wlanpi_core.utils.network_management.ns_exec")
    def test_set_default_route_fib_error(self, mock_ns_exec):
        """Test default route when FIB table doesn't exist."""
        # Mock FIB table error
        mock_ns_exec.side_effect = [
            RunCommandError("FIB table does not exist", 1),
            Mock(),  # Route set succeeds
        ]

        set_default_route("wlan0", "test_ns")

        assert mock_ns_exec.call_count == 2

    @patch("wlanpi_core.utils.network_management.ns_exec")
    def test_set_default_route_set_fails(self, mock_ns_exec):
        """Test default route when setting fails."""
        # Mock route show and set failure
        mock_ns_exec.side_effect = [
            Mock(stdout=""),  # No default route
            RunCommandError("Permission denied", 1),  # Route set fails
        ]

        # Should handle gracefully
        set_default_route("wlan0", "test_ns")

        assert mock_ns_exec.call_count == 2
