"""
Tests for namespace execution utilities.

Tests cover command execution in namespaces and root namespace,
error handling, and edge cases.
"""
import pytest
from unittest.mock import Mock, patch

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import (
    ns_exec,
    run_in_namespace,
    run_in_root,
)


class TestNsExec:
    """Tests for ns_exec function."""

    @patch("wlanpi_core.utils.namespace_execution.run_command")
    def test_ns_exec_in_namespace_success(self, mock_run_command):
        """Test successful command execution in a namespace."""
        mock_run_command.return_value = CommandResult("output", "", 0)

        result = ns_exec(["ip", "addr", "show"], namespace="test_ns")

        mock_run_command.assert_called_once_with(
            ["sudo", "ip", "netns", "exec", "test_ns", "ip", "addr", "show"],
            raise_on_fail=True,
        )
        assert result.stdout == "output"
        assert result.stderr == ""
        assert result.return_code == 0

    @patch("wlanpi_core.utils.namespace_execution.run_command")
    def test_ns_exec_in_root_success(self, mock_run_command):
        """Test successful command execution in root namespace."""
        mock_run_command.return_value = CommandResult("output", "", 0)

        result = ns_exec(["ip", "addr", "show"], namespace=None)

        mock_run_command.assert_called_once_with(
            ["sudo", "ip", "addr", "show"],
            raise_on_fail=True,
        )
        assert result.stdout == "output"
        assert result.return_code == 0

    @patch("wlanpi_core.utils.namespace_execution.run_command")
    def test_ns_exec_no_output_flag(self, mock_run_command):
        """Test that no_output flag is passed correctly."""
        mock_run_command.return_value = CommandResult("output", "", 0)

        result = ns_exec(["ls", "-l"], namespace="test_ns", no_output=True)

        mock_run_command.assert_called_once()
        assert result.stdout == "output"

    @patch("wlanpi_core.utils.namespace_execution.run_command")
    def test_ns_exec_raise_on_fail_false(self, mock_run_command):
        """Test that raise_on_fail=False prevents exception."""
        mock_run_command.return_value = CommandResult("", "error", 1)

        result = ns_exec(["invalid", "cmd"], namespace="test_ns", raise_on_fail=False)

        mock_run_command.assert_called_once_with(
            ["sudo", "ip", "netns", "exec", "test_ns", "invalid", "cmd"],
            raise_on_fail=False,
        )
        assert result.return_code == 1
        assert result.stderr == "error"

    @patch("wlanpi_core.utils.namespace_execution.run_command")
    def test_ns_exec_raises_on_failure(self, mock_run_command):
        """Test that RunCommandError is raised when command fails."""
        mock_run_command.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError) as exc_info:
            ns_exec(["invalid", "cmd"], namespace="test_ns")

        assert exc_info.value.return_code == 1
        assert "Command failed" in str(exc_info.value)

    @patch("wlanpi_core.utils.namespace_execution.run_command")
    def test_ns_exec_logs_errors(self, mock_run_command, caplog):
        """Test that errors are logged appropriately."""
        mock_run_command.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError):
            ns_exec(["invalid", "cmd"], namespace="test_ns")

        assert "Command failed" in caplog.text
        assert "test_ns" in caplog.text

    @patch("wlanpi_core.utils.namespace_execution.run_command")
    def test_ns_exec_with_complex_command(self, mock_run_command):
        """Test execution with complex command arguments."""
        mock_run_command.return_value = CommandResult("result", "", 0)

        result = ns_exec(
            ["wpa_cli", "-i", "wlan0", "status"],
            namespace="test_ns",
        )

        mock_run_command.assert_called_once_with(
            [
                "sudo",
                "ip",
                "netns",
                "exec",
                "test_ns",
                "wpa_cli",
                "-i",
                "wlan0",
                "status",
            ],
            raise_on_fail=True,
        )
        assert result.stdout == "result"


class TestRunInNamespace:
    """Tests for run_in_namespace convenience function."""

    @patch("wlanpi_core.utils.namespace_execution.ns_exec")
    def test_run_in_namespace_success(self, mock_ns_exec):
        """Test successful execution in namespace."""
        mock_ns_exec.return_value = CommandResult("output", "", 0)

        result = run_in_namespace("test_ns", ["ip", "addr", "show"])

        mock_ns_exec.assert_called_once_with(
            ["ip", "addr", "show"],
            namespace="test_ns",
            no_output=False,
            raise_on_fail=True,
        )
        assert result.stdout == "output"

    def test_run_in_namespace_raises_on_none(self):
        """Test that None namespace raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            run_in_namespace(None, ["ip", "addr", "show"])

        assert "cannot be None" in str(exc_info.value)
        assert "run_in_root" in str(exc_info.value)

    @patch("wlanpi_core.utils.namespace_execution.ns_exec")
    def test_run_in_namespace_with_options(self, mock_ns_exec):
        """Test run_in_namespace with custom options."""
        mock_ns_exec.return_value = CommandResult("output", "", 0)

        result = run_in_namespace(
            "test_ns",
            ["ls", "-l"],
            no_output=True,
            raise_on_fail=False,
        )

        mock_ns_exec.assert_called_once_with(
            ["ls", "-l"],
            namespace="test_ns",
            no_output=True,
            raise_on_fail=False,
        )
        assert result.stdout == "output"


class TestRunInRoot:
    """Tests for run_in_root convenience function."""

    @patch("wlanpi_core.utils.namespace_execution.ns_exec")
    def test_run_in_root_success(self, mock_ns_exec):
        """Test successful execution in root namespace."""
        mock_ns_exec.return_value = CommandResult("output", "", 0)

        result = run_in_root(["ip", "addr", "show"])

        mock_ns_exec.assert_called_once_with(
            ["ip", "addr", "show"],
            namespace=None,
            no_output=False,
            raise_on_fail=True,
        )
        assert result.stdout == "output"

    @patch("wlanpi_core.utils.namespace_execution.ns_exec")
    def test_run_in_root_with_options(self, mock_ns_exec):
        """Test run_in_root with custom options."""
        mock_ns_exec.return_value = CommandResult("output", "", 0)

        result = run_in_root(["ls", "-l"], no_output=True, raise_on_fail=False)

        mock_ns_exec.assert_called_once_with(
            ["ls", "-l"],
            namespace=None,
            no_output=True,
            raise_on_fail=False,
        )
        assert result.stdout == "output"

    @patch("wlanpi_core.utils.namespace_execution.ns_exec")
    def test_run_in_root_raises_on_failure(self, mock_ns_exec):
        """Test that run_in_root propagates RunCommandError."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        with pytest.raises(RunCommandError) as exc_info:
            run_in_root(["invalid", "cmd"])

        assert exc_info.value.return_code == 1
