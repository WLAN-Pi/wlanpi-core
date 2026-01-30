"""
Tests for WPA configuration generation.
"""
import pytest
from unittest.mock import Mock, patch

from wlanpi_core.schemas.network.network import (
    NamespaceConfig,
    RootConfig,
    NetworkModeEnum,
    NetSecurity,
    SecurityTypes,
)
from wlanpi_core.wpa.config import (
    generate_global_header,
    generate_network_block,
    write_wpa_config,
)


class TestGenerateGlobalHeader:
    """Tests for generate_global_header function."""

    def test_generate_global_header_default(self):
        """Test global header generation with defaults."""
        header = generate_global_header()

        assert "ctrl_interface=/run/wpa_supplicant" in header
        assert "update_config=1" in header
        assert "sae_pwe=2" in header

    def test_generate_global_header_custom(self):
        """Test global header generation with custom settings."""
        header = generate_global_header(
            ctrl_interface="/custom/path", update_config=0
        )

        assert "ctrl_interface=/custom/path" in header
        assert "update_config=0" in header
        assert "sae_pwe=2" in header


class TestGenerateNetworkBlock:
    """Tests for generate_network_block function."""

    @pytest.fixture
    def sample_config(self):
        """Create a sample namespace config."""
        return NamespaceConfig(
            namespace="test_ns",
            interface="wlan0",
            phy="phy0",
            iface_display_name="wlan0",
            mode=NetworkModeEnum.managed,
            security=NetSecurity(
                ssid="test_ssid",
                security=SecurityTypes.wpa2,
                psk="test_password",
            ),
        )

    def test_generate_network_block_wpa2(self, sample_config):
        """Test network block generation for WPA2."""
        block = generate_network_block(sample_config, priority=1)

        assert 'ssid="test_ssid"' in block
        assert "priority=1" in block
        assert 'psk="test_password"' in block
        assert "key_mgmt=WPA-PSK" in block
        assert "ieee80211w=1" in block

    def test_generate_network_block_open(self, sample_config):
        """Test network block generation for open network."""
        sample_config.security.security = SecurityTypes.open
        sample_config.security.psk = None

        block = generate_network_block(sample_config)

        assert "key_mgmt=NONE" in block
        assert "psk" not in block

    def test_generate_network_block_wpa3(self, sample_config):
        """Test network block generation for WPA3."""
        sample_config.security.security = SecurityTypes.wpa3
        sample_config.security.psk = "wpa3_password"

        block = generate_network_block(sample_config)

        assert "key_mgmt=SAE" in block
        assert "ieee80211w=2" in block
        assert 'psk="wpa3_password"' in block

    def test_generate_network_block_eap(self, sample_config):
        """Test network block generation for EAP (WPA2-EAP) when security is string-like."""
        # Schema SecurityTypes has no EAP member; config accepts str() for sec type
        from unittest.mock import MagicMock
        sample_config.security.security = MagicMock()
        sample_config.security.security.__str__ = lambda self: "WPA2-EAP"
        sample_config.security.identity = "user@example.com"
        sample_config.security.password = "eap_password"

        block = generate_network_block(sample_config)

        assert "key_mgmt=WPA-EAP" in block
        assert 'identity="user@example.com"' in block
        assert 'password="eap_password"' in block
        assert "eap=PEAP" in block

    def test_generate_network_block_missing_ssid(self, sample_config):
        """Test network block generation fails without SSID."""
        sample_config.security = None

        with pytest.raises(ValueError) as exc_info:
            generate_network_block(sample_config)

        assert "security.ssid is required" in str(exc_info.value)

    def test_generate_network_block_mlo(self, sample_config):
        """Test network block generation with MLO."""
        sample_config.mlo = True

        block = generate_network_block(sample_config)

        assert "mlo=1" in block


class TestWriteWpaConfig:
    """Tests for write_wpa_config function."""

    @pytest.fixture
    def sample_config(self):
        """Create a sample config."""
        return NamespaceConfig(
            namespace="test_ns",
            interface="wlan0",
            phy="phy0",
            iface_display_name="wlan0",
            mode=NetworkModeEnum.managed,
            security=NetSecurity(
                ssid="test_ssid",
                security=SecurityTypes.wpa2,
                psk="test_password",
            ),
        )

    def test_write_wpa_config_new_file(self, sample_config, tmp_path):
        """Test writing WPA config to new file."""
        write_wpa_config(
            sample_config,
            tmp_path,
            {"ctrl_interface": "/run/wpa_supplicant"},
        )

        conf_file = tmp_path / "wlan0.conf"
        assert conf_file.exists()
        content = conf_file.read_text()
        assert "ctrl_interface=" in content
        assert "test_ssid" in content

    def test_write_wpa_config_existing_file(self, sample_config, tmp_path):
        """Test writing WPA config when conf file already exists (appends block)."""
        (tmp_path / "wlan0.conf").write_text("ctrl_interface=/run/wpa_supplicant\n\n")
        write_wpa_config(
            sample_config,
            tmp_path,
            {"ctrl_interface": "/run/wpa_supplicant"},
        )
        content = (tmp_path / "wlan0.conf").read_text()
        assert "ctrl_interface=" in content
        assert "test_ssid" in content

    def test_write_wpa_config_missing_ssid(self, sample_config, tmp_path):
        """Test write_wpa_config fails without SSID."""
        sample_config.security = None

        with pytest.raises(ValueError) as exc_info:
            write_wpa_config(
                sample_config,
                tmp_path,
                {"ctrl_interface": "/run/wpa_supplicant"},
            )

        assert "security.ssid is required" in str(exc_info.value)
