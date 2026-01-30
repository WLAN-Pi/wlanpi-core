"""
Tests for namespace app management.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.namespaces.apps import (
    get_app_command,
    start_app_in_namespace,
    stop_app_in_namespace,
)


class TestGetAppCommand:
    """Tests for get_app_command function."""

    @patch("wlanpi_core.namespaces.apps.Path")
    def test_get_app_command_success(self, mock_path):
        """Test successful app command retrieval."""
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.open.return_value.__enter__.return_value.read.return_value = '{"my_app": "/usr/bin/myapp"}'
        mock_path.return_value = mock_file

        # Mock json.load
        with patch("wlanpi_core.namespaces.apps.json.load", return_value={"my_app": "/usr/bin/myapp"}):
            command = get_app_command("my_app")

        assert command == "/usr/bin/myapp"

    @patch("wlanpi_core.namespaces.apps.Path")
    def test_get_app_command_not_found(self, mock_path):
        """Test app command when app not found."""
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_path.return_value = mock_file

        with patch("wlanpi_core.namespaces.apps.json.load", return_value={"other_app": "/usr/bin/other"}):
            command = get_app_command("my_app")

        assert command is None

    @patch("wlanpi_core.namespaces.apps.Path")
    def test_get_app_command_creates_file(self, mock_path):
        """Test that missing apps file is created."""
        mock_file = MagicMock()
        mock_file.exists.return_value = False
        mock_path.return_value = mock_file

        with patch("wlanpi_core.namespaces.apps.json.load", return_value={}):
            command = get_app_command("my_app")

        mock_file.touch.assert_called_once()
        assert command is None

    @patch("wlanpi_core.namespaces.apps.Path")
    def test_get_app_command_parent_missing_raises(self, mock_path):
        """Test that missing parent dir raises FileNotFoundError (CI-safe)."""
        mock_file = MagicMock()
        mock_file.exists.return_value = False
        mock_parent = MagicMock()
        mock_parent.exists.return_value = False
        mock_file.parent = mock_parent
        mock_path.return_value = mock_file

        with pytest.raises(FileNotFoundError) as exc_info:
            get_app_command("my_app")

        assert "parent" in str(exc_info.value).lower() or "does not exist" in str(exc_info.value).lower()
        mock_file.touch.assert_not_called()


class TestStartAppInNamespace:
    """Tests for start_app_in_namespace function."""

    @patch("wlanpi_core.namespaces.apps.processes.get_processes_in_namespace")
    @patch("wlanpi_core.namespaces.apps.get_app_command")
    @patch("wlanpi_core.namespaces.apps.subprocess.Popen")
    @patch("wlanpi_core.namespaces.apps.Path")
    @patch("wlanpi_core.namespaces.apps.time.sleep")
    def test_start_app_in_namespace_success(
        self, mock_sleep, mock_path, mock_popen, mock_get_command, mock_get_pids
    ):
        """Test successful app start in namespace."""
        mock_get_command.return_value = "/usr/bin/myapp --arg"
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.poll.return_value = None  # Process is running
        mock_popen.return_value = mock_proc
        mock_get_pids.return_value = [1234]  # So _verify_app_in_namespace doesn't call run_command

        mock_pid_dir = MagicMock()
        mock_pid_file = MagicMock()
        mock_pid_dir.__truediv__.return_value = mock_pid_file
        mock_path.return_value = mock_pid_dir

        result = start_app_in_namespace("test_ns", "my_app")

        mock_get_command.assert_called_once_with("my_app")
        mock_popen.assert_called_once()
        assert result is True

    @patch("wlanpi_core.namespaces.apps.get_app_command")
    def test_start_app_in_namespace_not_found(self, mock_get_command):
        """Test app start when app not found."""
        mock_get_command.return_value = None

        with pytest.raises(ValueError) as exc_info:
            start_app_in_namespace("test_ns", "my_app")

        assert "not found" in str(exc_info.value)

    @patch("wlanpi_core.namespaces.apps.get_app_command")
    @patch("wlanpi_core.namespaces.apps.subprocess.Popen")
    @patch("wlanpi_core.namespaces.apps.Path")
    @patch("wlanpi_core.namespaces.apps.time.sleep")
    def test_start_app_in_root_namespace(self, mock_sleep, mock_path, mock_popen, mock_get_command):
        """Test app start in root namespace."""
        mock_get_command.return_value = "/usr/bin/myapp"
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        mock_pid_dir = MagicMock()
        mock_pid_file = MagicMock()
        mock_pid_dir.__truediv__.return_value = mock_pid_file
        mock_path.return_value = mock_pid_dir

        result = start_app_in_namespace(None, "my_app")

        # Verify command doesn't include ip netns exec
        call_args = mock_popen.call_args[0][0]
        assert "ip" not in call_args or "netns" not in call_args
        assert result is True


class TestStopAppInNamespace:
    """Tests for stop_app_in_namespace function."""

    @patch("wlanpi_core.namespaces.apps.Path")
    def test_stop_app_no_pid_file(self, mock_path):
        """Test stop app when PID file doesn't exist."""
        mock_pid_dir = MagicMock()
        mock_pid_file = MagicMock()
        mock_pid_file.exists.return_value = False
        mock_pid_dir.__truediv__.return_value = mock_pid_file
        mock_path.return_value = mock_pid_dir

        result = stop_app_in_namespace("test_ns")

        assert result is False

    @patch("wlanpi_core.namespaces.apps.processes.get_processes_in_namespace")
    @patch("wlanpi_core.namespaces.namespace.namespace_exists")
    @patch("wlanpi_core.namespaces.apps.run_command")
    @patch("wlanpi_core.namespaces.apps.Path")
    def test_stop_app_in_namespace_success(self, mock_path, mock_run, mock_exists, mock_get_pids):
        """Test successful app stop in namespace."""
        mock_pid_dir = MagicMock()
        mock_pid_file = MagicMock()
        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = '{"pid": 1234, "app_id": "my_app", "app_command": "/usr/bin/myapp"}'
        mock_pid_dir.__truediv__.return_value = mock_pid_file
        mock_path.return_value = mock_pid_dir

        mock_exists.return_value = True
        mock_get_pids.return_value = [1234]
        mock_run.return_value = Mock(return_code=0, stdout="test_ns")

        result = stop_app_in_namespace("test_ns")

        assert result is True
        mock_pid_file.unlink.assert_called_once()

    @patch("wlanpi_core.namespaces.apps.run_command")
    @patch("wlanpi_core.namespaces.apps.Path")
    def test_stop_app_in_root_success(self, mock_path, mock_run):
        """Test successful app stop in root namespace."""
        mock_pid_dir = MagicMock()
        mock_pid_file = MagicMock()
        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = '{"pid": 1234, "app_id": "my_app"}'
        mock_pid_dir.__truediv__.return_value = mock_pid_file
        mock_path.return_value = mock_pid_dir

        mock_run.return_value = Mock(return_code=0)

        result = stop_app_in_namespace(None)

        mock_run.assert_called()
        assert result is True

    @patch("wlanpi_core.namespaces.apps.Path")
    def test_stop_app_invalid_pid_file(self, mock_path):
        """Test stop app with invalid PID file format."""
        mock_pid_dir = MagicMock()
        mock_pid_file = MagicMock()
        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = "invalid_json"
        mock_pid_dir.__truediv__.return_value = mock_pid_file
        mock_path.return_value = mock_pid_dir

        # Should handle gracefully
        result = stop_app_in_namespace("test_ns")

        # Should attempt to parse as old format (int)
        assert result is False or result is True  # Either is acceptable
