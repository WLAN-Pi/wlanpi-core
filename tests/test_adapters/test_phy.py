"""
Tests for PHY operations.
"""
import pytest
from unittest.mock import Mock, patch

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.adapters.phy import (
    get_phy_info,
    list_phys,
    move_phy_to_namespace,
    move_phy_to_root,
)


class TestListPhys:
    """Tests for list_phys function."""

    @patch("wlanpi_core.adapters.phy.run_command")
    def test_list_phys_in_root(self, mock_run_command):
        """Test listing PHYs in root namespace."""
        mock_run_command.return_value = CommandResult(
            "Wiphy phy0\n    * 2412 MHz [1] (20.0 dBm)\nWiphy phy1\n",
            "",
            0,
        )

        phys = list_phys()

        mock_run_command.assert_called_once()
        assert "phy0" in phys
        assert "phy1" in phys
        assert len(phys) == 2

    @patch("wlanpi_core.adapters.phy.ns_exec")
    def test_list_phys_in_namespace(self, mock_ns_exec):
        """Test listing PHYs in a namespace."""
        mock_ns_exec.return_value = CommandResult(
            "Wiphy phy0\n",
            "",
            0,
        )

        phys = list_phys(namespace="test_ns")

        mock_ns_exec.assert_called_once()
        assert "phy0" in phys

    @patch("wlanpi_core.adapters.phy.run_command")
    def test_list_phys_empty(self, mock_run_command):
        """Test PHY listing when no PHYs exist."""
        mock_run_command.return_value = CommandResult("", "", 0)

        phys = list_phys()

        assert phys == []

    @patch("wlanpi_core.adapters.phy.run_command")
    def test_list_phys_failure(self, mock_run_command):
        """Test PHY listing failure."""
        mock_run_command.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            list_phys()


class TestGetPhyInfo:
    """Tests for get_phy_info function."""

    @patch("wlanpi_core.adapters.phy.list_phys")
    @patch("wlanpi_core.adapters.phy.run_command")
    def test_get_phy_info_success(self, mock_run_command, mock_list):
        """Test successful PHY info retrieval."""
        mock_list.return_value = ["phy0", "phy1"]
        mock_run_command.return_value = CommandResult(
            "Wiphy phy0\n    max # scan SSIDs: 20\n",
            "",
            0,
        )

        info = get_phy_info("phy0")

        assert info is not None
        assert info["name"] == "phy0"
        assert info["exists"] is True

    @patch("wlanpi_core.adapters.phy.list_phys")
    def test_get_phy_info_not_found(self, mock_list):
        """Test PHY info when PHY doesn't exist."""
        mock_list.return_value = ["phy0", "phy1"]

        info = get_phy_info("phy2")

        assert info is None

    def test_get_phy_info_empty_name(self):
        """Test that empty PHY name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_phy_info("")

        assert "cannot be empty" in str(exc_info.value)


class TestMovePhyToNamespace:
    """Tests for move_phy_to_namespace function."""

    @patch("wlanpi_core.adapters.phy.run_command")
    def test_move_phy_success(self, mock_run_command):
        """Test successful PHY move to namespace."""
        mock_run_command.return_value = CommandResult("", "", 0)

        result = move_phy_to_namespace("phy0", "test_ns")

        mock_run_command.assert_called_once()
        assert result is True

    def test_move_phy_empty_phy(self):
        """Test that empty PHY name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            move_phy_to_namespace("", "test_ns")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.adapters.phy.run_command")
    def test_move_phy_failure(self, mock_run_command):
        """Test PHY move when command fails."""
        mock_run_command.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            move_phy_to_namespace("phy0", "test_ns")


class TestMovePhyToRoot:
    """Tests for move_phy_to_root function."""

    @patch("wlanpi_core.adapters.phy.ns_exec")
    def test_move_phy_to_root_success(self, mock_ns_exec):
        """Test successful PHY move to root."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = move_phy_to_root("phy0", "test_ns")

        mock_ns_exec.assert_called_once()
        assert result is True

    def test_move_phy_to_root_empty_phy(self):
        """Test that empty PHY name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            move_phy_to_root("", "test_ns")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.adapters.phy.ns_exec")
    def test_move_phy_to_root_failure(self, mock_ns_exec):
        """Test PHY move when command fails."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            move_phy_to_root("phy0", "test_ns")
