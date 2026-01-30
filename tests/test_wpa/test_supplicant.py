"""
Tests for WPA supplicant process management.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.wpa.supplicant import (
    kill_all_supplicants,
    parse_wpa_log,
    start_or_restart_supplicant,
)


class TestStartOrRestartSupplicant:
    """Tests for start_or_restart_supplicant function."""

    @patch("wlanpi_core.wpa.supplicant.ns_exec")
    @patch("wlanpi_core.wpa.supplicant.Path")
    def test_start_supplicant_in_namespace(self, mock_path, mock_ns_exec):
        """Test starting supplicant in namespace."""
        mock_log_file = Mock()
        mock_log_file.exists.return_value = False
        mock_path.return_value = mock_log_file
        mock_ns_exec.return_value = Mock()

        start_or_restart_supplicant(
            "wlan0",
            "test_ns",
            Path("/etc/wpa_supplicant/wlan0.conf"),
        )

        # Should kill existing, remove socket, and start new
        assert mock_ns_exec.call_count >= 3

    @patch("wlanpi_core.wpa.supplicant.ns_exec")
    @patch("wlanpi_core.wpa.supplicant.Path")
    def test_start_supplicant_in_root(self, mock_path, mock_ns_exec):
        """Test starting supplicant in root namespace."""
        mock_log_file = Mock()
        mock_log_file.exists.return_value = True
        mock_path.return_value = mock_log_file
        mock_ns_exec.return_value = Mock()

        start_or_restart_supplicant(
            "wlan0",
            None,
            Path("/etc/wpa_supplicant/wlan0.conf"),
        )

        assert mock_ns_exec.call_count >= 3

    @patch("wlanpi_core.wpa.supplicant.ns_exec")
    @patch("wlanpi_core.wpa.supplicant.Path")
    def test_start_supplicant_handles_errors(self, mock_path, mock_ns_exec):
        """Test that supplicant start handles cleanup errors gracefully."""
        mock_log_file = Mock()
        mock_log_file.exists.return_value = False
        mock_path.return_value = mock_log_file
        # First call (pkill) fails, but should continue
        mock_ns_exec.side_effect = [
            RunCommandError("Process not found", 1),  # pkill fails
            Mock(),  # rm succeeds
            Mock(),  # start succeeds
        ]

        # Should not raise
        start_or_restart_supplicant(
            "wlan0",
            "test_ns",
            Path("/etc/wpa_supplicant/wlan0.conf"),
        )


class TestParseWpaLog:
    """Tests for parse_wpa_log function."""

    @patch("wlanpi_core.wpa.supplicant.Path")
    @patch("wlanpi_core.wpa.supplicant.time.sleep")
    @patch("wlanpi_core.wpa.supplicant.time.time")
    def test_parse_wpa_log_success(self, mock_time, mock_sleep, mock_path):
        """Test successful WPA log parsing."""
        mock_log_file = Mock()
        mock_log_file.exists.return_value = True
        mock_file_handle = Mock()
        mock_file_handle.readline.side_effect = [
            "1234567890.123: Some log line\n",
            "1234567891.456: CTRL-EVENT-CONNECTED - Connection completed\n",
            "",  # extra so iterator does not exhaust and raise StopIteration
        ]
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_file_handle
        mock_cm.__exit__.return_value = None
        mock_log_file.open.return_value = mock_cm
        mock_path.return_value = mock_log_file
        mock_time.return_value = 0  # So log.info() and timeout check don't exhaust side_effect

        # Should not raise
        parse_wpa_log("wlan0", timeout=30)

    @patch("wlanpi_core.wpa.supplicant.Path")
    @patch("wlanpi_core.wpa.supplicant.time.sleep")
    @patch("wlanpi_core.wpa.supplicant.time.time")
    def test_parse_wpa_log_timeout(self, mock_time, mock_sleep, mock_path):
        """Test WPA log parsing timeout."""
        mock_log_file = Mock()
        mock_log_file.exists.return_value = True
        mock_file_handle = Mock()
        mock_file_handle.readline.return_value = ""  # No more lines
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_file_handle
        mock_cm.__exit__.return_value = None
        mock_log_file.open.return_value = mock_cm
        mock_path.return_value = mock_log_file
        mock_time.side_effect = [0, 31]  # Timeout exceeded

        with pytest.raises(TimeoutError) as exc_info:
            parse_wpa_log("wlan0", timeout=30)

        assert "Timeout" in str(exc_info.value)

    @patch("wlanpi_core.wpa.supplicant.Path")
    def test_parse_wpa_log_file_not_exists(self, mock_path):
        """Test WPA log parsing when file doesn't exist."""
        mock_log_file = Mock()
        mock_log_file.exists.return_value = False
        mock_path.return_value = mock_log_file

        # Should handle gracefully
        parse_wpa_log("wlan0", timeout=30)


class TestKillAllSupplicants:
    """Tests for kill_all_supplicants function."""

    @patch("wlanpi_core.utils.general.run_command")
    def test_kill_all_supplicants_success(self, mock_run):
        """Test successful kill of all supplicants."""
        mock_run.return_value = Mock(return_code=0)

        # Should not raise
        kill_all_supplicants()

        mock_run.assert_called_once()

    @patch("wlanpi_core.utils.general.run_command")
    def test_kill_all_supplicants_handles_errors(self, mock_run):
        """Test that kill_all_supplicants handles errors gracefully."""
        mock_run.side_effect = Exception("Command failed")

        # Should not raise
        kill_all_supplicants()
