import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pytest

from wlanpi_core.services.partitions.config_service import ConfigService


class TestConfigService:
    """Tests for the ConfigService class."""

    @pytest.fixture
    def mock_device_service(self):
        """Create a mock device service that always passes validation."""
        mock = MagicMock()
        mock.is_allowed_device.return_value = True
        return mock

    @pytest.fixture
    def mock_partition_service(self):
        """Create a mock partition service with required functionality."""
        mock = MagicMock()
        mock.get_current_partition_set.return_value = "A"
        mock.get_inactive_partition_set.return_value = "B"
        mock.is_mounted.return_value = True
        mock.BOOT1_PATH = "/dev/mmcblk0p1"
        mock.BOOT2_PATH = "/dev/mmcblk0p2"
        mock.ROOT1_PATH = "/dev/mmcblk0p5"
        mock.ROOT2_PATH = "/dev/mmcblk0p6"
        return mock

    @pytest.fixture
    def config_service(self, mock_device_service, mock_partition_service):
        """Create a config service with mocked dependencies."""
        with patch(
            "wlanpi_core.services.partitions.config_service.DeviceService",
            return_value=mock_device_service,
        ), patch(
            "wlanpi_core.services.partitions.config_service.PartitionService",
            return_value=mock_partition_service,
        ):
            service = ConfigService()
            service.BACKUP_DIR = tempfile.mkdtemp()
            yield service
            if os.path.exists(service.BACKUP_DIR):
                for filename in os.listdir(service.BACKUP_DIR):
                    os.unlink(os.path.join(service.BACKUP_DIR, filename))
                os.rmdir(service.BACKUP_DIR)

    def test_backup_config(self, config_service):
        """Test backing up a configuration file."""
        with tempfile.NamedTemporaryFile(delete=False) as test_file:
            test_file.write(b"test content")
            test_file_path = test_file.name

        try:
            backup_path = config_service.backup_config(test_file_path)

            assert os.path.exists(backup_path)

            with open(backup_path, "r") as f:
                content = f.read()
                assert content == "test content"
        finally:
            if os.path.exists(test_file_path):
                os.unlink(test_file_path)

    def test_restore_config(self, config_service):
        """Test restoring a configuration file from backup."""
        # Create a temporary file and back it up
        with tempfile.NamedTemporaryFile(delete=False) as test_file:
            test_file.write(b"original content")
            test_file_path = test_file.name

        try:
            config_service.backup_config(test_file_path)

            with open(test_file_path, "w") as f:
                f.write("modified content")

            result = config_service.restore_config(test_file_path)
            assert result is True

            with open(test_file_path, "r") as f:
                content = f.read()
                assert content == "original content"
        finally:
            if os.path.exists(test_file_path):
                os.unlink(test_file_path)

    @patch("wlanpi_core.services.partitions.config_service.tempfile.mkdtemp")
    @patch("wlanpi_core.services.partitions.config_service.os.path.exists")
    @patch(
        "builtins.open",
        new_callable=unittest.mock.mock_open,
        read_data="console=tty1 root=PARTUUID=12345678-01 rootwait",
    )
    def test_update_cmdline_txt(
        self,
        mock_open,
        mock_exists,
        mock_mkdtemp,
        config_service,
        mock_partition_service,
    ):
        """Test updating cmdline.txt with a new root UUID."""
        mock_exists.return_value = True
        mock_mkdtemp.return_value = "/tmp/mock_dir"
        mock_partition_service.is_mounted.return_value = False
        config_service.partition_service = mock_partition_service

        result = config_service.update_cmdline_txt("/dev/mmcblk0p1", "87654321-01")

        assert result is True
        mock_open.assert_called()
        handle = mock_open()

        handle.write.assert_called_once_with(
            "console=tty1 root=PARTUUID=87654321-01 rootwait"
        )

    @patch("wlanpi_core.services.partitions.config_service.tempfile.mkdtemp")
    @patch("wlanpi_core.services.partitions.config_service.os.path.exists")
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_create_tryboot_txt(
        self,
        mock_open,
        mock_exists,
        mock_mkdtemp,
        config_service,
        mock_partition_service,
    ):
        """Test creating tryboot.txt for one-time boot."""
        mock_exists.return_value = True
        mock_mkdtemp.return_value = "/tmp/mock_dir"
        mock_partition_service.is_mounted.return_value = False
        config_service.partition_service = mock_partition_service

        result = config_service.create_tryboot_txt("/dev/mmcblk0p1", 2)

        assert result is True
        mock_open.assert_called()
        handle = mock_open()

        handle.write.assert_called_once_with("boot_partition=2\n")

    @patch("wlanpi_core.services.partitions.config_service.run_command")
    def test_tryboot_alternate_partition(
        self, mock_run_command, config_service, mock_partition_service
    ):
        """Test configuring system to boot from alternate partition."""
        mock_run_command.return_value.stdout = "/dev/mmcblk0p1"
        config_service.create_tryboot_txt = MagicMock(return_value=True)

        result = config_service.tryboot_alternate_partition()

        assert result is True
        config_service.create_tryboot_txt.assert_called_once_with("/dev/mmcblk0p1", 2)

    @patch("wlanpi_core.services.partitions.config_service.tempfile.mkdtemp")
    @patch("wlanpi_core.services.partitions.config_service.os.path.exists")
    @patch(
        "builtins.open",
        new_callable=unittest.mock.mock_open,
        read_data="PARTUUID=12345678-07 /home    ext4    defaults,noatime 0 2",
    )
    def test_update_fstab(
        self,
        mock_open,
        mock_exists,
        mock_mkdtemp,
        config_service,
        mock_partition_service,
    ):
        """Test updating fstab with new home UUID."""
        mock_exists.return_value = True
        mock_mkdtemp.return_value = "/tmp/mock_dir"
        mock_partition_service.is_mounted.return_value = False
        config_service.partition_service = mock_partition_service

        result = config_service.update_fstab("/dev/mmcblk0p5", "87654321-07")

        assert result is True
        mock_open.assert_called()
        handle = mock_open()

        handle.write.assert_called_once_with(
            "PARTUUID=87654321-07 /home    ext4    defaults,noatime 0 2"
        )

    def test_prepare_partition_update(self, config_service, mock_partition_service):
        """Test preparing configuration for partition update."""
        mock_partition_service.get_set_paths.return_value = {
            "boot": "/dev/mmcblk0p2",
            "root": "/dev/mmcblk0p6",
        }
        mock_partition_service.get_partition_uuids.return_value = {
            "boot1": "uuid-boot1",
            "boot2": "uuid-boot2",
            "root1": "uuid-root1",
            "root2": "uuid-root2",
            "home": "uuid-home",
        }
        config_service.partition_service = mock_partition_service

        result = config_service.prepare_partition_update("B")

        assert result["success"] is True
        assert result["target_set"] == "B"
        assert result["source_set"] == "A"
        assert result["target_boot"] == "/dev/mmcblk0p2"
        assert result["target_root"] == "/dev/mmcblk0p6"
        assert result["target_boot_uuid"] == "uuid-boot2"
        assert result["target_root_uuid"] == "uuid-root2"
        assert result["home_uuid"] == "uuid-home"
