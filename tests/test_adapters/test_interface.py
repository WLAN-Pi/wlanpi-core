"""
Tests for interface operations.
"""
import pytest
from unittest.mock import Mock, patch

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.adapters.interface import (
    bring_interface_down,
    bring_interface_up,
    create_interface,
    delete_interface,
    get_interface_info,
)


class TestCreateInterface:
    """Tests for create_interface function."""

    @patch("wlanpi_core.adapters.interface.run_command")
    def test_create_interface_in_root(self, mock_run_command):
        """Test creating interface in root namespace."""
        mock_run_command.return_value = CommandResult("", "", 0)

        result = create_interface("phy0", "wlan0", "managed")

        mock_run_command.assert_called_once()
        assert result is True

    @patch("wlanpi_core.adapters.interface.ns_exec")
    def test_create_interface_in_namespace(self, mock_ns_exec):
        """Test creating interface in a namespace."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = create_interface("phy0", "wlan0", "managed", namespace="test_ns")

        mock_ns_exec.assert_called_once()
        assert result is True

    @patch("wlanpi_core.adapters.interface.run_command")
    def test_create_interface_already_exists(self, mock_run_command):
        """Test creating interface when it already exists."""
        mock_run_command.side_effect = RunCommandError("File exists", 1)

        # Should handle gracefully
        result = create_interface("phy0", "wlan0", "managed")

        assert result is True

    def test_create_interface_empty_phy(self):
        """Test that empty PHY name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            create_interface("", "wlan0")

        assert "cannot be empty" in str(exc_info.value)

    def test_create_interface_empty_name(self):
        """Test that empty interface name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            create_interface("phy0", "")

        assert "cannot be empty" in str(exc_info.value)


class TestDeleteInterface:
    """Tests for delete_interface function."""

    @patch("wlanpi_core.adapters.interface.run_command")
    def test_delete_interface_success(self, mock_run_command):
        """Test successful interface deletion."""
        mock_run_command.return_value = CommandResult("", "", 0)

        result = delete_interface("wlan0")

        mock_run_command.assert_called_once()
        assert result is True

    @patch("wlanpi_core.adapters.interface.ns_exec")
    def test_delete_interface_in_namespace(self, mock_ns_exec):
        """Test deleting interface in a namespace."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = delete_interface("wlan0", namespace="test_ns")

        mock_ns_exec.assert_called_once()
        assert result is True

    @patch("wlanpi_core.adapters.interface.run_command")
    def test_delete_interface_not_exists(self, mock_run_command):
        """Test deleting interface when it doesn't exist."""
        mock_run_command.side_effect = RunCommandError("No such device", 1)

        # Should handle gracefully
        result = delete_interface("wlan0")

        assert result is True

    def test_delete_interface_empty_name(self):
        """Test that empty interface name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            delete_interface("")

        assert "cannot be empty" in str(exc_info.value)


class TestGetInterfaceInfo:
    """Tests for get_interface_info function."""

    @patch("wlanpi_core.adapters.interface.run_command")
    def test_get_interface_info_success(self, mock_run_command):
        """Test successful interface info retrieval."""
        mock_run_command.return_value = CommandResult(
            "Interface wlan0\n    wiphy 0\n    type managed\n",
            "",
            0,
        )

        info = get_interface_info("wlan0")

        assert info is not None
        assert info["name"] == "wlan0"
        assert info["exists"] is True
        assert info.get("phy") == "phy0"

    @patch("wlanpi_core.adapters.interface.run_command")
    def test_get_interface_info_not_found(self, mock_run_command):
        """Test interface info when interface doesn't exist."""
        mock_run_command.side_effect = RunCommandError("No such device", 1)

        info = get_interface_info("wlan0")

        assert info is None

    def test_get_interface_info_empty_name(self):
        """Test that empty interface name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_interface_info("")

        assert "cannot be empty" in str(exc_info.value)


class TestBringInterfaceUpDown:
    """Tests for bring_interface_up and bring_interface_down functions."""

    @patch("wlanpi_core.adapters.interface.run_command")
    def test_bring_interface_up_in_root(self, mock_run_command):
        """Test bringing interface up in root namespace."""
        mock_run_command.return_value = CommandResult("", "", 0)

        result = bring_interface_up("wlan0")

        mock_run_command.assert_called_once()
        assert result is True

    @patch("wlanpi_core.adapters.interface.ns_exec")
    def test_bring_interface_up_in_namespace(self, mock_ns_exec):
        """Test bringing interface up in a namespace."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = bring_interface_up("wlan0", namespace="test_ns")

        mock_ns_exec.assert_called_once()
        assert result is True

    @patch("wlanpi_core.adapters.interface.run_command")
    def test_bring_interface_down(self, mock_run_command):
        """Test bringing interface down."""
        mock_run_command.return_value = CommandResult("", "", 0)

        result = bring_interface_down("wlan0")

        mock_run_command.assert_called_once()
        assert result is True

    def test_bring_interface_empty_name(self):
        """Test that empty interface name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            bring_interface_up("")

        assert "cannot be empty" in str(exc_info.value)
