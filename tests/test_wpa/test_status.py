"""
Tests for WPA status checking.
"""
import pytest
from unittest.mock import Mock, patch

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.wpa.status import get_wpa_status, parse_key_mgmt


class TestGetWpaStatus:
    """Tests for get_wpa_status function."""

    @patch("wlanpi_core.wpa.status.ns_exec")
    def test_get_wpa_status_success(self, mock_ns_exec):
        """Test successful WPA status retrieval."""
        # Mock wpa_cli status
        mock_ns_exec.side_effect = [
            Mock(stdout="wpa_state=COMPLETED\nssid=test_ssid\nbssid=aa:bb:cc:dd:ee:ff\nfreq=2412\n"),
            Mock(stdout="aa:bb:cc:dd:ee:ff\t2412\t-45\t[WPA2-PSK-CCMP][ESS]\ttest_ssid\n"),
            Mock(stdout="2: wlan0: <BROADCAST,MULTICAST,UP> ..."),
        ]

        status = get_wpa_status("wlan0", "test_ns")

        assert "wpa_status" in status
        assert status["wpa_status"]["wpa_state"] == "COMPLETED"
        assert status["wpa_status"]["ssid"] == "test_ssid"
        assert "connected_scan" in status
        assert status["connected_scan"]["ssid"] == "test_ssid"

    @patch("wlanpi_core.wpa.status.ns_exec")
    def test_get_wpa_status_failure(self, mock_ns_exec):
        """Test WPA status when command fails."""
        mock_ns_exec.side_effect = RunCommandError("Command failed", 1)

        status = get_wpa_status("wlan0", "test_ns")

        assert "error" in status
        assert "Command failed" in status["error"]

    @patch("wlanpi_core.wpa.status.ns_exec")
    def test_get_wpa_status_in_root(self, mock_ns_exec):
        """Test WPA status in root namespace."""
        mock_ns_exec.side_effect = [
            Mock(stdout="wpa_state=COMPLETED\n"),
            Mock(stdout=""),
            Mock(stdout=""),
        ]

        status = get_wpa_status("wlan0", None)

        assert "wpa_status" in status


class TestParseKeyMgmt:
    """Tests for parse_key_mgmt function."""

    def test_parse_key_mgmt_wpa2(self):
        """Test parsing WPA2-PSK key management."""
        key_mgmt = parse_key_mgmt("[WPA2-PSK-CCMP][ESS]")

        assert key_mgmt == "wpa-psk"

    def test_parse_key_mgmt_wpa(self):
        """Test parsing WPA-PSK key management."""
        key_mgmt = parse_key_mgmt("[WPA-PSK-TKIP][ESS]")

        assert key_mgmt == "wpa-psk"

    def test_parse_key_mgmt_wep(self):
        """Test parsing WEP key management."""
        key_mgmt = parse_key_mgmt("[WEP][ESS]")

        assert key_mgmt == "wep"

    def test_parse_key_mgmt_open(self):
        """Test parsing open network key management."""
        key_mgmt = parse_key_mgmt("[ESS]")

        assert key_mgmt == "open"

    def test_parse_key_mgmt_unknown(self):
        """Test parsing unknown key management."""
        key_mgmt = parse_key_mgmt("[UNKNOWN]")

        assert key_mgmt == "unknown"
