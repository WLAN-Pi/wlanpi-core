"""
Tests for namespace interface management.
"""
import pytest
from unittest.mock import Mock, patch

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.namespaces.interfaces import (
    bring_interface_down,
    bring_interface_up,
    get_interfaces_in_namespace,
    move_interface_to_namespace,
    move_interface_to_root,
)


class TestGetInterfacesInNamespace:
    """Tests for get_interfaces_in_namespace function."""

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_get_interfaces_success(self, mock_ns_exec):
        """Test successful interface listing."""
        mock_ns_exec.return_value = CommandResult(
            "1: lo: <LOOPBACK,UP> ...\n2: wlan0: <BROADCAST,MULTICAST,UP> ...\n3: eth0: <BROADCAST,MULTICAST> ...\n",
            "",
            0,
        )

        interfaces = get_interfaces_in_namespace("test_ns")

        mock_ns_exec.assert_called_once_with(
            ["ip", "-o", "link", "show"],
            namespace="test_ns",
            no_output=True,
        )
        assert "wlan0" in interfaces
        assert "eth0" in interfaces
        assert "lo" not in interfaces  # Loopback excluded by default

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_get_interfaces_with_loopback(self, mock_ns_exec):
        """Test interface listing with loopback included."""
        mock_ns_exec.return_value = CommandResult(
            "1: lo: <LOOPBACK,UP> ...\n2: wlan0: <BROADCAST,MULTICAST,UP> ...\n",
            "",
            0,
        )

        interfaces = get_interfaces_in_namespace("test_ns", include_loopback=True)

        assert "lo" in interfaces
        assert "wlan0" in interfaces

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_get_interfaces_empty(self, mock_ns_exec):
        """Test interface listing when no interfaces exist."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        interfaces = get_interfaces_in_namespace("test_ns")

        assert interfaces == []

    def test_get_interfaces_empty_namespace(self):
        """Test that empty namespace raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_interfaces_in_namespace("")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_get_interfaces_failure(self, mock_ns_exec):
        """Test interface listing failure."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            get_interfaces_in_namespace("test_ns")


class TestMoveInterfaceToNamespace:
    """Tests for move_interface_to_namespace function."""

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_move_wlan_interface(self, mock_ns_exec):
        """Test moving a wireless interface."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = move_interface_to_namespace("wlan0", "test_ns")

        mock_ns_exec.assert_called_once_with(
            ["ip", "link", "set", "wlan0", "netns", "test_ns"],
            namespace=None,
        )
        assert result is True

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_move_eth_interface(self, mock_ns_exec):
        """Test moving an ethernet interface."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = move_interface_to_namespace("eth0", "test_ns")

        mock_ns_exec.assert_called_once_with(
            ["ip", "link", "set", "eth0", "netns", "test_ns"],
            namespace=None,
        )
        assert result is True

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_move_interface_with_type(self, mock_ns_exec):
        """Test moving interface with explicit type."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = move_interface_to_namespace("wlan0", "test_ns", interface_type="wlan")

        assert result is True

    def test_move_interface_empty_interface(self):
        """Test that empty interface name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            move_interface_to_namespace("", "test_ns")

        assert "cannot be empty" in str(exc_info.value)

    def test_move_interface_empty_namespace(self):
        """Test that empty namespace raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            move_interface_to_namespace("wlan0", "")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_move_interface_failure(self, mock_ns_exec):
        """Test moving interface when command fails."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            move_interface_to_namespace("wlan0", "test_ns")


class TestMoveInterfaceToRoot:
    """Tests for move_interface_to_root function."""

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_move_to_root_success(self, mock_ns_exec):
        """Test successful move to root namespace."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = move_interface_to_root("wlan0", "test_ns")

        mock_ns_exec.assert_called_once_with(
            ["ip", "link", "set", "wlan0", "netns", "1"],
            namespace="test_ns",
        )
        assert result is True

    def test_move_to_root_empty_interface(self):
        """Test that empty interface name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            move_interface_to_root("", "test_ns")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_move_to_root_failure(self, mock_ns_exec):
        """Test move to root when command fails."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            move_interface_to_root("wlan0", "test_ns")


class TestBringInterfaceUpDown:
    """Tests for bring_interface_up and bring_interface_down functions."""

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_bring_interface_up_in_namespace(self, mock_ns_exec):
        """Test bringing interface up in a namespace."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = bring_interface_up("wlan0", "test_ns")

        mock_ns_exec.assert_called_once_with(
            ["ip", "link", "set", "wlan0", "up"],
            namespace="test_ns",
        )
        assert result is True

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_bring_interface_up_in_root(self, mock_ns_exec):
        """Test bringing interface up in root namespace."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = bring_interface_up("wlan0", None)

        mock_ns_exec.assert_called_once_with(
            ["ip", "link", "set", "wlan0", "up"],
            namespace=None,
        )
        assert result is True

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_bring_interface_down(self, mock_ns_exec):
        """Test bringing interface down."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = bring_interface_down("wlan0", "test_ns")

        mock_ns_exec.assert_called_once_with(
            ["ip", "link", "set", "wlan0", "down"],
            namespace="test_ns",
        )
        assert result is True

    def test_bring_interface_empty_name(self):
        """Test that empty interface name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            bring_interface_up("", "test_ns")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.namespaces.interfaces.ns_exec")
    def test_bring_interface_failure(self, mock_ns_exec):
        """Test bringing interface up when command fails."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            bring_interface_up("wlan0", "test_ns")
