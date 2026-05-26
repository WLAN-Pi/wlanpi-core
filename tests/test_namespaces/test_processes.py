"""
Tests for namespace process management.
"""
import pytest
from unittest.mock import Mock, patch

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.namespaces.processes import (
    get_process_info,
    get_processes_in_namespace,
    kill_process_in_namespace,
    kill_processes_in_namespace,
)


class TestGetProcessesInNamespace:
    """Tests for get_processes_in_namespace function."""

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_get_processes_success(self, mock_ns_exec):
        """Test successful process listing."""
        mock_ns_exec.return_value = CommandResult("1234\n5678\n9012\n", "", 0)

        pids = get_processes_in_namespace("test_ns")

        mock_ns_exec.assert_called_once_with(
            ["ip", "netns", "pids", "test_ns"],
            namespace=None,
            no_output=True,
        )
        assert 1234 in pids
        assert 5678 in pids
        assert 9012 in pids
        assert len(pids) == 3

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_get_processes_empty(self, mock_ns_exec):
        """Test process listing when no processes exist."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        pids = get_processes_in_namespace("test_ns")

        assert pids == []

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_get_processes_with_whitespace(self, mock_ns_exec):
        """Test process listing with whitespace in output."""
        mock_ns_exec.return_value = CommandResult("  1234  \n  5678  \n", "", 0)

        pids = get_processes_in_namespace("test_ns")

        assert 1234 in pids
        assert 5678 in pids

    def test_get_processes_empty_namespace(self):
        """Test that empty namespace raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_processes_in_namespace("")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_get_processes_failure(self, mock_ns_exec):
        """Test process listing failure."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            get_processes_in_namespace("test_ns")


class TestKillProcessInNamespace:
    """Tests for kill_process_in_namespace function."""

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_kill_process_success(self, mock_ns_exec):
        """Test successful process kill."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = kill_process_in_namespace(1234, "test_ns")

        mock_ns_exec.assert_called_once_with(
            ["kill", "-TERM", "1234"],
            namespace="test_ns",
        )
        assert result is True

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_kill_process_with_signal(self, mock_ns_exec):
        """Test killing process with specific signal."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        result = kill_process_in_namespace(1234, "test_ns", signal="KILL")

        mock_ns_exec.assert_called_once_with(
            ["kill", "-KILL", "1234"],
            namespace="test_ns",
        )
        assert result is True

    def test_kill_process_invalid_pid(self):
        """Test that invalid PID raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            kill_process_in_namespace(-1, "test_ns")

        assert "Invalid PID" in str(exc_info.value)

    def test_kill_process_empty_namespace(self):
        """Test that empty namespace raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            kill_process_in_namespace(1234, "")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_kill_process_failure(self, mock_ns_exec):
        """Test killing process when command fails."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            kill_process_in_namespace(1234, "test_ns")


class TestKillProcessesInNamespace:
    """Tests for kill_processes_in_namespace function."""

    @patch("wlanpi_core.namespaces.processes.get_processes_in_namespace")
    @patch("wlanpi_core.namespaces.processes.kill_process_in_namespace")
    def test_kill_all_processes(self, mock_kill, mock_get_pids):
        """Test killing all processes in namespace."""
        mock_get_pids.return_value = [1234, 5678, 9012]
        mock_kill.return_value = True

        count = kill_processes_in_namespace("test_ns")

        assert mock_kill.call_count == 3
        assert count == 3

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_kill_processes_by_name(self, mock_ns_exec):
        """Test killing processes by name pattern."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        count = kill_processes_in_namespace("test_ns", process_name="wpa_supplicant")

        mock_ns_exec.assert_called_once_with(
            ["pkill", "-TERM", "-f", "wpa_supplicant"],
            namespace="test_ns",
        )
        assert count == 1  # Indicates operation was attempted

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_kill_processes_by_name_not_found(self, mock_ns_exec):
        """Test killing processes by name when none found."""
        mock_ns_exec.side_effect = RunCommandError("No such process", 1)

        # Should handle gracefully
        count = kill_processes_in_namespace("test_ns", process_name="nonexistent")

        assert count == 0

    @patch("wlanpi_core.namespaces.processes.get_processes_in_namespace")
    @patch("wlanpi_core.namespaces.processes.kill_process_in_namespace")
    def test_kill_processes_partial_failure(self, mock_kill, mock_get_pids):
        """Test killing processes when some fail."""
        mock_get_pids.return_value = [1234, 5678, 9012]
        mock_kill.side_effect = [True, RunCommandError("Failed", 1), True]

        count = kill_processes_in_namespace("test_ns")

        assert mock_kill.call_count == 3
        assert count == 2  # Two successful kills

    def test_kill_processes_empty_namespace(self):
        """Test that empty namespace raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            kill_processes_in_namespace("")

        assert "cannot be empty" in str(exc_info.value)


class TestGetProcessInfo:
    """Tests for get_process_info function."""

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_get_process_info_success(self, mock_ns_exec):
        """Test successful process info retrieval."""
        mock_ns_exec.return_value = CommandResult("1234 /usr/bin/test_app\n", "", 0)

        info = get_process_info(1234, "test_ns")

        mock_ns_exec.assert_called_once_with(
            ["ps", "-p", "1234", "-o", "pid,cmd", "--no-headers"],
            namespace="test_ns",
            no_output=True,
        )
        assert info["pid"] == 1234
        assert "test_app" in info["cmd"]

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_get_process_info_not_found(self, mock_ns_exec):
        """Test process info when process doesn't exist."""
        mock_ns_exec.return_value = CommandResult("", "", 0)

        info = get_process_info(1234, "test_ns")

        assert info["pid"] == 1234
        assert info["exists"] is False

    @patch("wlanpi_core.namespaces.processes.ns_exec")
    def test_get_process_info_failure(self, mock_ns_exec):
        """Test process info when command fails."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        info = get_process_info(1234, "test_ns")

        assert info["pid"] == 1234
        assert info["exists"] is False

    def test_get_process_info_invalid_pid(self):
        """Test that invalid PID raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_process_info(-1, "test_ns")

        assert "Invalid PID" in str(exc_info.value)
