import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from wlanpi_core.services.partitions.config_service import ConfigService
from wlanpi_core.services.partitions.image_handler import ImageHandler
from wlanpi_core.services.partitions.lock_service import LockService
from wlanpi_core.services.partitions.partition_service import PartitionService
from wlanpi_core.services.partitions.update_manager import UpdateError, UpdateManager


@pytest.fixture
def mock_services():
    """Fixture to create mock services."""
    mock_lock_service = MagicMock(spec=LockService)
    mock_partition_service = MagicMock(spec=PartitionService)
    mock_config_service = MagicMock(spec=ConfigService)
    mock_image_handler = MagicMock(spec=ImageHandler)

    mock_partition_service.get_current_partition_set.return_value = "A"
    mock_partition_service.get_inactive_partition_set.return_value = "B"
    mock_partition_service.get_set_paths.return_value = {
        "boot": "/dev/mmcblk0p2",
        "root": "/dev/mmcblk0p6",
    }
    mock_partition_service.get_partition_uuids.return_value = {
        "boot1": "boot1-uuid",
        "boot2": "boot2-uuid",
        "root1": "root1-uuid",
        "root2": "root2-uuid",
        "home": "home-uuid",
    }
    mock_partition_service.check_available_space.return_value = (
        1024 * 1024 * 1024
    )  # 1GB

    mock_image_handler.analyze_image.return_value = {
        "size": 1024 * 1024 * 1024,  # 1GB
        "size_human": "1.00 GB",
        "partitions": [
            {
                "device": "test",
                "start": 0,
                "end": 1000,
                "sectors": 1000,
                "size": "100M",
                "type": "boot",
            },
            {
                "device": "test",
                "start": 1000,
                "end": 10000,
                "sectors": 9000,
                "size": "900M",
                "type": "root",
            },
        ],
        "partition_count": 2,
    }
    mock_image_handler.calculate_space_requirements.return_value = {
        "boot": 100 * 1024 * 1024,  # 100MB
        "root": 900 * 1024 * 1024,  # 900MB
        "total": 1024 * 1024 * 1024,  # 1GB
        "boot_human": "100.00 MB",
        "root_human": "900.00 MB",
        "total_human": "1.00 GB",
    }
    mock_image_handler.verify_image_checksum.return_value = True
    mock_image_handler.extract_boot_partition.return_value = True
    mock_image_handler.extract_root_partition.return_value = True
    mock_image_handler.validate_extracted_partitions.return_value = True

    mock_config_service.update_cmdline_txt.return_value = True
    mock_config_service.update_fstab.return_value = True

    return {
        "lock_service": mock_lock_service,
        "partition_service": mock_partition_service,
        "config_service": mock_config_service,
        "image_handler": mock_image_handler,
    }


@pytest.fixture
def update_manager(mock_services):
    """Create an UpdateManager with mocked dependencies and a temporary status directory."""
    temp_dir = tempfile.mkdtemp()

    with patch("wlanpi_core.services.partitions.update_manager.os.makedirs"):
        manager = UpdateManager(
            mock_services["lock_service"],
            mock_services["partition_service"],
            mock_services["config_service"],
            mock_services["image_handler"],
        )
        manager.STATUS_DIR = temp_dir

    yield manager

    for file in os.listdir(temp_dir):
        os.unlink(os.path.join(temp_dir, file))
    os.rmdir(temp_dir)


@patch("os.path.exists")
def test_prepare_update_success(mock_exists, update_manager, mock_services):
    """Test successful preparation for update."""
    mock_exists.return_value = True
    image_handler = mock_services["image_handler"]
    partition_service = mock_services["partition_service"]

    test_image_path = "/path/to/test/image.img"
    result = update_manager.prepare_update(test_image_path)

    assert result["success"] is True
    assert result["message"] == "Prerequisites check completed successfully"

    mock_exists.assert_called_with(test_image_path)
    image_handler.verify_image_checksum.assert_called_once()
    image_handler.analyze_image.assert_called_once_with(test_image_path)
    image_handler.calculate_space_requirements.assert_called_once_with(test_image_path)
    partition_service.check_available_space.assert_called()

    assert update_manager._status == "preparing"
    assert update_manager._target_set == "B"


@patch("os.path.exists")
def test_prepare_update_image_not_found(mock_exists, update_manager):
    """Test preparation with missing image file."""
    mock_exists.return_value = False
    test_image_path = "/path/to/missing/image.img"

    with pytest.raises(UpdateError) as exc_info:
        update_manager.prepare_update(test_image_path)

    assert "Image file not found" in str(exc_info.value)
    assert update_manager._status == "failed"


@patch("os.path.exists")
def test_prepare_update_insufficient_boot_space(
    mock_exists, update_manager, mock_services
):
    """Test preparation with insufficient boot partition space."""
    mock_exists.return_value = True
    partition_service = mock_services["partition_service"]

    partition_service.check_available_space.side_effect = [
        50 * 1024 * 1024,  # 50MB for boot (less than the 100MB required)
        1024 * 1024 * 1024,  # 1GB for root (enough)
    ]

    test_image_path = "/path/to/test/image.img"

    with pytest.raises(UpdateError) as exc_info:
        update_manager.prepare_update(test_image_path)

    assert "Insufficient space on boot partition" in str(exc_info.value)
    assert update_manager._status == "failed"


@patch("os.path.exists")
def test_prepare_update_insufficient_root_space(
    mock_exists, update_manager, mock_services
):
    """Test preparation with insufficient root partition space."""
    mock_exists.return_value = True
    partition_service = mock_services["partition_service"]

    partition_service.check_available_space.side_effect = [
        200 * 1024 * 1024,  # 200MB for boot (enough)
        500 * 1024 * 1024,  # 500MB for root (less than the 900MB required)
    ]

    test_image_path = "/path/to/test/image.img"

    with pytest.raises(UpdateError) as exc_info:
        update_manager.prepare_update(test_image_path)

    assert "Insufficient space on root partition" in str(exc_info.value)
    assert update_manager._status == "failed"


@patch("os.path.exists")
def test_prepare_update_checksum_failure(mock_exists, update_manager, mock_services):
    """Test preparation with checksum verification failure."""
    mock_exists.return_value = True
    image_handler = mock_services["image_handler"]

    image_handler.verify_image_checksum.return_value = False

    test_image_path = "/path/to/test/image.img"

    with pytest.raises(UpdateError) as exc_info:
        update_manager.prepare_update(test_image_path)

    assert "checksum verification failed" in str(exc_info.value)
    assert update_manager._status == "failed"

    image_handler.verify_image_checksum.return_value = True


@patch("os.path.exists")
def test_execute_update_success(mock_exists, update_manager, mock_services):
    """Test successful update execution."""
    mock_exists.return_value = True
    image_handler = mock_services["image_handler"]
    config_service = mock_services["config_service"]

    test_image_path = "/path/to/test/image.img"
    update_manager.prepare_update(test_image_path)

    result = update_manager.execute_update(test_image_path)

    assert result["success"] is True
    assert result["message"] == "Update completed successfully"

    image_handler.extract_boot_partition.assert_called_once_with(
        test_image_path, "/dev/mmcblk0p2"
    )
    image_handler.extract_root_partition.assert_called_once_with(
        test_image_path, "/dev/mmcblk0p6"
    )
    image_handler.validate_extracted_partitions.assert_called_once_with("B")
    config_service.update_cmdline_txt.assert_called_once_with(
        "/dev/mmcblk0p2", "root2-uuid"
    )
    config_service.update_fstab.assert_called_once_with("/dev/mmcblk0p6", "home-uuid")

    assert update_manager._status == "completed"
    assert update_manager._progress == 100


@patch("os.path.exists")
def test_execute_update_without_preparation(mock_exists, update_manager):
    """Test executing update without preparation."""
    mock_exists.return_value = True

    test_image_path = "/path/to/test/image.img"

    result = update_manager.execute_update(test_image_path)

    assert result["success"] is True
    assert update_manager._status == "completed"


@patch("os.path.exists")
def test_execute_update_extraction_failure(mock_exists, update_manager, mock_services):
    """Test update execution with extraction failure."""
    mock_exists.return_value = True
    image_handler = mock_services["image_handler"]

    image_handler.extract_boot_partition.return_value = False

    test_image_path = "/path/to/test/image.img"
    update_manager.prepare_update(test_image_path)

    update_manager.execute_update(test_image_path)

    image_handler.extract_boot_partition.return_value = True


@patch("os.path.exists")
def test_execute_update_validation_failure(mock_exists, update_manager, mock_services):
    """Test update execution with validation failure."""
    mock_exists.return_value = True
    image_handler = mock_services["image_handler"]

    image_handler.validate_extracted_partitions.return_value = False

    test_image_path = "/path/to/test/image.img"
    update_manager.prepare_update(test_image_path)

    with pytest.raises(UpdateError) as exc_info:
        update_manager.execute_update(test_image_path)

    assert "Partition verification failed" in str(exc_info.value)
    assert update_manager._status == "failed"

    image_handler.validate_extracted_partitions.return_value = True


def test_get_update_status(update_manager):
    """Test getting update status."""
    update_manager._status = "completed"
    update_manager._current_step = "finalize_update"
    update_manager._progress = 100
    update_manager._target_set = "B"
    update_manager._start_time = "2023-01-01T00:00:00"
    update_manager._end_time = "2023-01-01T00:10:00"
    update_manager._update_details = {"test": "details"}

    status = update_manager.get_update_status()

    assert status["status"] == "completed"
    assert status["current_step"] == "finalize_update"
    assert status["progress"] == 100
    assert status["target_set"] == "B"
    assert status["start_time"] == "2023-01-01T00:00:00"
    assert status["end_time"] == "2023-01-01T00:10:00"
    assert status["details"] == {"test": "details"}


@patch("os.path.exists")
def test_get_update_history_empty(mock_exists, update_manager, monkeypatch):
    """Test getting empty update history."""
    mock_exists.return_value = True

    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: MagicMock(
            __enter__=lambda self: MagicMock(
                read=lambda: "[]", __iter__=lambda: iter([])
            ),
            __exit__=lambda self, *args: None,
        ),
    )

    history = update_manager.get_update_history()
    assert history == []


@patch("os.path.exists")
def test_get_update_history_with_entries(mock_exists, update_manager, monkeypatch):
    """Test getting update history with entries."""
    mock_exists.return_value = True

    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: MagicMock(
            __enter__=lambda self: MagicMock(
                read=lambda: '[{"id": 1, "timestamp": "2023-01-01T00:00:00", "status": "completed"}]',
                __iter__=lambda: iter([]),
            ),
            __exit__=lambda self, *args: None,
        ),
    )

    history = update_manager.get_update_history()

    assert len(history) == 1
    assert history[0]["id"] == 1
    assert history[0]["timestamp"] == "2023-01-01T00:00:00"


def test_verify_update_success(update_manager, mock_services):
    """Test successful update verification."""
    partition_service = mock_services["partition_service"]

    update_manager._status = "completed"
    update_manager._target_set = "A"  # The set that was updated

    partition_service.get_current_partition_set.return_value = "A"

    result = update_manager.verify_update()

    assert result["success"] is True
    assert "Successfully booted" in result["message"]


def test_verify_update_failure(update_manager, mock_services):
    """Test failed update verification."""
    partition_service = mock_services["partition_service"]

    update_manager._status = "completed"
    update_manager._target_set = "B"

    partition_service.get_current_partition_set.return_value = "A"

    result = update_manager.verify_update()

    assert result["success"] is False
    assert "Not running on updated partition set" in result["message"]


def test_rollback_update(update_manager, mock_services):
    """Test rollback functionality."""
    partition_service = mock_services["partition_service"]
    config_service = mock_services["config_service"]

    partition_service.get_current_partition_set.return_value = "A"

    config_service.create_tryboot_txt.return_value = True

    result = update_manager.rollback_update()

    assert result["success"] is True
    assert "Rollback configuration created" in result["message"]

    config_service.create_tryboot_txt.assert_called_once_with(
        partition_service.BOOT1_PATH, 2  # Rolling back to set B
    )


def test_rollback_update_failure(update_manager, mock_services):
    """Test rollback with tryboot configuration failure."""
    partition_service = mock_services["partition_service"]
    config_service = mock_services["config_service"]

    partition_service.get_current_partition_set.return_value = "A"

    config_service.create_tryboot_txt.return_value = False

    with pytest.raises(UpdateError) as exc_info:
        update_manager.rollback_update()

    assert "Failed to create tryboot configuration for rollback" in str(exc_info.value)

    config_service.create_tryboot_txt.return_value = True
