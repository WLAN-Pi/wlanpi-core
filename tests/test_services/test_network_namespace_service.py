"""
Integration tests for NetworkNamespaceService.

These tests verify that the refactored service correctly orchestrates
the new namespace, adapter, and interface modules.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.schemas.network.network import (
    NamespaceConfig,
    RootConfig,
    NetworkModeEnum,
    NetSecurity,
    SecurityTypes,
)
from wlanpi_core.services.network_namespace_service import NetworkNamespaceService


@pytest.fixture
def service():
    """Create a NetworkNamespaceService instance for testing."""
    return NetworkNamespaceService()


@pytest.fixture
def sample_namespace_config():
    """Create a sample namespace configuration."""
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
        default_route=False,
        autostart_app=None,
    )


@pytest.fixture
def sample_root_config():
    """Create a sample root namespace configuration."""
    return RootConfig(
        interface="wlan0",
        phy="phy0",
        iface_display_name="wlan0",
        mode=NetworkModeEnum.managed,
        security=NetSecurity(
            ssid="test_ssid",
            security=SecurityTypes.wpa2,
            psk="test_password",
        ),
        default_route=False,
        autostart_app=None,
    )


class TestGetInterfaces:
    """Tests for get_interfaces method."""

    @patch("wlanpi_core.services.network_namespace_service.discovery.list_interfaces")
    def test_get_interfaces_delegates_to_discovery(self, mock_list, service):
        """Test that get_interfaces delegates to discovery module."""
        mock_list.return_value = ["wlan0", "wlan1"]

        result = service.get_interfaces()

        mock_list.assert_called_once()
        assert result == ["wlan0", "wlan1"]


class TestPrepareNamespace:
    """Tests for _prepare_namespace method."""

    @patch("wlanpi_core.services.network_namespace_service.interface.bring_interface_up")
    @patch("wlanpi_core.services.network_namespace_service.interface.create_interface")
    @patch("wlanpi_core.services.network_namespace_service.phy.move_phy_to_namespace")
    @patch("wlanpi_core.services.network_namespace_service.phy.move_phy_to_root")
    @patch("wlanpi_core.services.network_namespace_service.phy.list_phys")
    @patch("wlanpi_core.services.network_namespace_service.interface.delete_interface")
    @patch("wlanpi_core.services.network_namespace_service.ns_namespace.create_namespace")
    @patch("wlanpi_core.services.network_namespace_service.ns_namespace.namespace_exists")
    def test_prepare_namespace_uses_new_modules(
        self,
        mock_exists,
        mock_create,
        mock_delete,
        mock_list_phys,
        mock_move_to_root,
        mock_move_to_ns,
        mock_create_iface,
        mock_bring_up,
        service,
        sample_namespace_config,
    ):
        """Test that _prepare_namespace uses the new modules."""
        mock_exists.return_value = False
        mock_list_phys.return_value = []  # PHY not in namespace
        mock_delete.side_effect = RunCommandError("No such device", 1)

        result = service._prepare_namespace(sample_namespace_config)

        # Verify namespace operations
        mock_exists.assert_called_once_with("test_ns")
        mock_create.assert_called_once_with("test_ns")

        # Verify interface operations
        mock_delete.assert_called_once_with("wlan0", namespace="test_ns")

        # Verify PHY operations
        mock_list_phys.assert_called_once_with(namespace="test_ns")
        mock_move_to_ns.assert_called_once_with("phy0", "test_ns")

        # Verify interface creation
        mock_create_iface.assert_called_once()
        mock_bring_up.assert_called_once_with("wlan0", namespace="test_ns")

        assert result is True

    @patch("wlanpi_core.services.network_namespace_service.interface.bring_interface_up")
    @patch("wlanpi_core.services.network_namespace_service.interface.create_interface")
    @patch("wlanpi_core.services.network_namespace_service.phy.move_phy_to_namespace")
    @patch("wlanpi_core.services.network_namespace_service.phy.move_phy_to_root")
    @patch("wlanpi_core.services.network_namespace_service.phy.list_phys")
    @patch("wlanpi_core.services.network_namespace_service.interface.delete_interface")
    @patch("wlanpi_core.services.network_namespace_service.ns_namespace.namespace_exists")
    def test_prepare_namespace_existing_namespace(
        self,
        mock_exists,
        mock_delete,
        mock_list_phys,
        mock_move_to_root,
        mock_move_to_ns,
        mock_create_iface,
        mock_bring_up,
        service,
        sample_namespace_config,
    ):
        """Test _prepare_namespace when namespace already exists."""
        mock_exists.return_value = True
        mock_list_phys.return_value = []  # PHY not in namespace

        result = service._prepare_namespace(sample_namespace_config)

        # Should not create namespace
        mock_exists.assert_called_once()
        # Should still move PHY and create interface
        mock_move_to_ns.assert_called_once()
        assert result is True


class TestPrepareRoot:
    """Tests for _prepare_root method."""

    @patch("wlanpi_core.services.network_namespace_service.interface.bring_interface_up")
    @patch("wlanpi_core.services.network_namespace_service.interface.create_interface")
    @patch("wlanpi_core.services.network_namespace_service.interface.delete_interface")
    @patch("wlanpi_core.services.network_namespace_service.run_command")
    def test_prepare_root_uses_new_modules(
        self,
        mock_run,
        mock_delete,
        mock_create_iface,
        mock_bring_up,
        service,
        sample_root_config,
    ):
        """Test that _prepare_root runs and uses interface module where refactored."""
        from wlanpi_core.models.command_result import CommandResult
        mock_delete.side_effect = RunCommandError("No such device", 1)
        # _prepare_root uses _run(["iw", "phy"], ...) and _run(["iw", "phy", phy, ...])
        mock_run.return_value = CommandResult(stdout="phy0\nphy1", stderr="", return_code=0)

        result = service._prepare_root(sample_root_config)

        mock_delete.assert_called_once_with("wlan0", namespace=None)
        assert mock_run.call_count >= 1
        assert result is True


class TestRevertToRoot:
    """Tests for revert_to_root method."""

    @patch("wlanpi_core.services.network_namespace_service.ns_namespace.delete_namespace")
    @patch("wlanpi_core.services.network_namespace_service.ns_namespace.list_namespaces")
    @patch("wlanpi_core.services.network_namespace_service.ns_interfaces.get_interfaces_in_namespace")
    @patch("wlanpi_core.services.network_namespace_service.processes.kill_processes_in_namespace")
    def test_revert_to_root_all_namespaces(
        self,
        mock_kill,
        mock_get_interfaces,
        mock_list_ns,
        mock_delete_ns,
        service,
    ):
        """Test revert_to_root when reverting all namespaces."""
        mock_list_ns.return_value = ["test_ns1", "test_ns2"]
        mock_get_interfaces.return_value = ["wlan0"]

        service.revert_to_root(cfg=None, delete_namespace=True)

        # Should list namespaces
        mock_list_ns.assert_called()

        # Should get interfaces for each namespace
        assert mock_get_interfaces.call_count >= 1

        # Should delete namespaces
        assert mock_delete_ns.call_count >= 1


class TestServiceIntegration:
    """Integration tests for service orchestration."""

    @patch("wlanpi_core.services.network_namespace_service.wpa_supplicant.start_or_restart_supplicant")
    @patch("wlanpi_core.services.network_namespace_service.write_dhcp_config")
    @patch("wlanpi_core.services.network_namespace_service.wpa_config.write_wpa_config")
    @patch("wlanpi_core.services.network_namespace_service.interface.bring_interface_up")
    @patch("wlanpi_core.services.network_namespace_service.interface.create_interface")
    @patch("wlanpi_core.services.network_namespace_service.phy.move_phy_to_namespace")
    @patch("wlanpi_core.services.network_namespace_service.phy.list_phys")
    @patch("wlanpi_core.services.network_namespace_service.interface.delete_interface")
    @patch("wlanpi_core.services.network_namespace_service.ns_namespace.create_namespace")
    @patch("wlanpi_core.services.network_namespace_service.ns_namespace.namespace_exists")
    @patch("wlanpi_core.services.network_namespace_service.discovery.list_interfaces")
    def test_activate_config_namespace_integration(
        self,
        mock_list_interfaces,
        mock_exists,
        mock_create_ns,
        mock_delete,
        mock_list_phys,
        mock_move_phy,
        mock_create_iface,
        mock_bring_up,
        mock_wpa_config,
        mock_dhcp_config,
        mock_supplicant,
        service,
        sample_namespace_config,
    ):
        """Test full integration of activate_config for namespace config."""
        mock_list_interfaces.return_value = ["wlan0"]
        mock_exists.return_value = False
        mock_list_phys.return_value = []
        mock_delete.side_effect = RunCommandError("No such device", 1)

        # Mock validation to pass
        with patch.object(service, "_validate_config", return_value=(True, "")):
            result = service.activate_config(sample_namespace_config)

        # Verify all modules were called
        mock_list_interfaces.assert_called()
        mock_exists.assert_called()
        mock_create_ns.assert_called()
        mock_move_phy.assert_called()
        mock_create_iface.assert_called()
        mock_bring_up.assert_called()

        # Should return a status
        assert result is not None
        assert hasattr(result, "status")

    @patch("wlanpi_core.services.network_namespace_service.discovery.list_interfaces")
    def test_activate_config_interface_not_found(
        self,
        mock_list_interfaces,
        service,
        sample_namespace_config,
    ):
        """Test activate_config when interface doesn't exist."""
        mock_list_interfaces.return_value = []  # No interfaces

        # Mock validation to pass
        with patch.object(service, "_validate_config", return_value=(True, "")):
            result = service.activate_config(sample_namespace_config)

        # Should return "provisioned" status when interface not found
        assert result.status == "provisioned"
