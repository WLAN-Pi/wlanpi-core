"""
Tests for interface discovery operations.
"""
import pytest
from unittest.mock import Mock, patch

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.adapters.discovery import get_interface_by_name, list_interfaces


class TestListInterfaces:
    """Tests for list_interfaces function."""

    @patch("wlanpi_core.adapters.discovery.run_command")
    def test_list_interfaces_success(self, mock_run_command):
        """Test successful interface listing."""
        mock_run_command.return_value = CommandResult(
            "Interface wlan0\n    ifindex 3\nInterface wlan1\n    ifindex 4\n",
            "",
            0,
        )

        interfaces = list_interfaces()

        mock_run_command.assert_called_once()
        assert "wlan0" in interfaces
        assert "wlan1" in interfaces
        assert len(interfaces) == 2

    @patch("wlanpi_core.adapters.discovery.run_command")
    def test_list_interfaces_empty(self, mock_run_command):
        """Test interface listing when no interfaces exist."""
        mock_run_command.return_value = CommandResult("", "", 0)

        interfaces = list_interfaces()

        assert interfaces == []

    @patch("wlanpi_core.adapters.discovery.run_command")
    def test_list_interfaces_failure(self, mock_run_command):
        """Test interface listing failure."""
        mock_run_command.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            list_interfaces()


class TestGetInterfaceByName:
    """Tests for get_interface_by_name function."""

    @patch("wlanpi_core.adapters.discovery.list_interfaces")
    @patch("wlanpi_core.adapters.discovery.run_command")
    def test_get_interface_success(self, mock_run_command, mock_list):
        """Test successful interface info retrieval."""
        mock_list.return_value = ["wlan0", "wlan1"]
        mock_run_command.return_value = CommandResult(
            "Interface wlan0\n    wiphy 0\n    type managed\n",
            "",
            0,
        )

        info = get_interface_by_name("wlan0")

        assert info is not None
        assert info["name"] == "wlan0"
        assert info["exists"] is True
        assert info.get("phy") == "phy0"

    @patch("wlanpi_core.adapters.discovery.list_interfaces")
    def test_get_interface_not_found(self, mock_list):
        """Test interface info when interface doesn't exist."""
        mock_list.return_value = ["wlan0", "wlan1"]

        info = get_interface_by_name("wlan2")

        assert info is None

    def test_get_interface_empty_name(self):
        """Test that empty interface name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_interface_by_name("")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.adapters.discovery.list_interfaces")
    @patch("wlanpi_core.adapters.discovery.run_command")
    def test_get_interface_failure(self, mock_run_command, mock_list):
        """Test interface info when command fails."""
        mock_list.return_value = ["wlan0"]
        mock_run_command.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            get_interface_by_name("wlan0")
