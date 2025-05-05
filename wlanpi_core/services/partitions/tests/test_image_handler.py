import hashlib
from unittest.mock import MagicMock, patch

import pytest

from wlanpi_core.services.partitions.image_handler import (
    ImageExtractionError,
    ImageHandler,
    ImageHandlerError,
    ImageVerificationError,
)


@pytest.fixture
def image_handler():
    """Create an ImageHandler instance for testing."""
    return ImageHandler()


@pytest.fixture
def sample_image_data():
    """Create sample image structure data."""
    return {
        "partitions": [
            {
                "device": "/dev/loop0p1",
                "start": 8192,
                "end": 532479,
                "sectors": 524288,
                "size": "256M",
                "type": "c W95 FAT32 (LBA)",
            },
            {
                "device": "/dev/loop0p2",
                "start": 532480,
                "end": 9625599,
                "sectors": 9093120,
                "size": "4.3G",
                "type": "83 Linux",
            },
        ],
        "size": 4831838208,  # About 4.8 GB
        "size_human": "4.83 GB",
        "partition_count": 2,
    }


@pytest.fixture
def mock_fdisk_output():
    """Mock output from fdisk command."""
    return (
        "Disk /path/to/test/image.img: 4.8 GiB, 4831838208 bytes, 9437968 sectors\n"
        "Units: sectors of 1 * 512 = 512 bytes\n"
        "Sector size (logical/physical): 512 bytes / 512 bytes\n"
        "I/O size (minimum/optimal): 512 bytes / 512 bytes\n"
        "Disklabel type: dos\n"
        "Disk identifier: 0x5452574f\n\n"
        "/path/to/test/image.img1      8192    532479    524288  256M  c W95 FAT32 (LBA)\n"
        "/path/to/test/image.img2    532480   9625599   9093120  4.3G 83 Linux"
    )


def test_format_size(image_handler):
    """Test the _format_size method."""
    assert image_handler._format_size(1024) == "1.00 KB"
    assert image_handler._format_size(1024 * 1024) == "1.00 MB"
    assert image_handler._format_size(1024 * 1024 * 1024) == "1.00 GB"
    assert image_handler._format_size(500) == "500.00 B"
    assert image_handler._format_size(1024 * 1024 * 1024 * 5) == "5.00 TB"


def test_parse_size(image_handler):
    """Test the _parse_size method."""
    assert image_handler._parse_size("1K") == 1024
    assert image_handler._parse_size("1M") == 1024 * 1024
    assert image_handler._parse_size("1G") == 1024 * 1024 * 1024
    assert image_handler._parse_size("500") == 500
    assert image_handler._parse_size("2.5G") == int(2.5 * 1024 * 1024 * 1024)


@patch("os.path.exists")
@patch("subprocess.run")
def test_analyze_image_success(
    mock_run, mock_exists, image_handler, mock_fdisk_output, sample_image_data
):
    """Test successful image analysis."""
    mock_exists.return_value = True
    mock_process = MagicMock()
    mock_process.stdout = mock_fdisk_output
    mock_process.returncode = 0
    mock_run.return_value = mock_process

    result = image_handler.analyze_image("/path/to/test/image.img")

    assert "size" in result
    assert "size_human" in result
    assert "partitions" in result
    assert "partition_count" in result

    assert len(result["partitions"]) == 2
    assert result["partitions"][0]["device"] == "/path/to/test/image.img1"
    assert result["partitions"][0]["size"] == "256M"
    assert result["partitions"][1]["device"] == "/path/to/test/image.img2"
    assert result["partitions"][1]["size"] == "4.3G"

    mock_run.assert_called_once()


@patch("os.path.exists")
def test_analyze_image_file_not_found(mock_exists, image_handler):
    """Test image analysis with non-existent file."""
    mock_exists.return_value = False

    with pytest.raises(ImageHandlerError) as exc_info:
        image_handler.analyze_image("/path/to/nonexistent/image.img")

    assert "Image file not found" in str(exc_info.value)


@patch("os.path.exists")
@patch("subprocess.run")
def test_analyze_image_fdisk_error(mock_run, mock_exists, image_handler):
    """Test image analysis with fdisk error."""
    mock_exists.return_value = True
    mock_run.side_effect = Exception("fdisk error")

    with pytest.raises(ImageHandlerError) as exc_info:
        image_handler.analyze_image("/path/to/test/image.img")

    assert "Failed to analyze image" in str(exc_info.value)


@patch("os.path.exists")
def test_verify_image_checksum_success(mock_exists, image_handler, monkeypatch):
    """Test successful checksum verification."""
    mock_exists.side_effect = [True, True]

    test_content = b"test content"
    expected_checksum = hashlib.sha256(test_content).hexdigest()

    checksum_file_content = f"{expected_checksum}  image.img"

    mock_files = {
        "/path/to/test/image.img": test_content,
        "/path/to/test/image.img.sha256": checksum_file_content.encode(),
    }

    def mock_open_wrapper(filename, *args, **kwargs):
        if filename in mock_files:
            return MagicMock(
                __enter__=lambda self: MagicMock(
                    read=lambda: (
                        mock_files[filename].decode()
                        if isinstance(mock_files[filename], bytes)
                        else mock_files[filename]
                    ),
                    __iter__=lambda: (
                        iter(mock_files[filename].decode().splitlines())
                        if isinstance(mock_files[filename], bytes)
                        else iter(mock_files[filename].splitlines())
                    ),
                    readlines=lambda: (
                        mock_files[filename].decode().splitlines()
                        if isinstance(mock_files[filename], bytes)
                        else mock_files[filename].splitlines()
                    ),
                ),
                __exit__=lambda self, *args: None,
            )
        return open(filename, *args, **kwargs)

    def mock_open_binary(filename, *args, **kwargs):
        if filename in mock_files:
            return MagicMock(
                __enter__=lambda self: MagicMock(
                    read=lambda size=None: (
                        mock_files[filename]
                        if size is None
                        else mock_files[filename][:size]
                    ),
                    __iter__=lambda: iter([mock_files[filename]]),
                ),
                __exit__=lambda self, *args: None,
            )
        return open(filename, *args, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open_wrapper)

    monkeypatch.setattr(
        "hashlib.sha256",
        lambda: MagicMock(
            update=lambda chunk: None, hexdigest=lambda: expected_checksum
        ),
    )

    result = image_handler.verify_image_checksum("/path/to/test/image.img")

    assert result is True


@patch("os.path.exists")
def test_verify_image_checksum_failure(mock_exists, image_handler, monkeypatch):
    """Test failed checksum verification."""
    mock_exists.side_effect = [True, True]

    test_content = b"test content"
    actual_checksum = hashlib.sha256(test_content).hexdigest()
    wrong_checksum = "0" * 64  # Definitely wrong

    checksum_file_content = f"{wrong_checksum}  image.img"

    mock_files = {
        "/path/to/test/image.img": test_content,
        "/path/to/test/image.img.sha256": checksum_file_content.encode(),
    }

    def mock_open_wrapper(filename, *args, **kwargs):
        if filename in mock_files:
            return MagicMock(
                __enter__=lambda self: MagicMock(
                    read=lambda: (
                        mock_files[filename].decode()
                        if isinstance(mock_files[filename], bytes)
                        else mock_files[filename]
                    ),
                    __iter__=lambda: (
                        iter(mock_files[filename].decode().splitlines())
                        if isinstance(mock_files[filename], bytes)
                        else iter(mock_files[filename].splitlines())
                    ),
                    readlines=lambda: (
                        mock_files[filename].decode().splitlines()
                        if isinstance(mock_files[filename], bytes)
                        else mock_files[filename].splitlines()
                    ),
                ),
                __exit__=lambda self, *args: None,
            )
        return open(filename, *args, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open_wrapper)

    monkeypatch.setattr(
        "hashlib.sha256",
        lambda: MagicMock(update=lambda chunk: None, hexdigest=lambda: actual_checksum),
    )

    result = image_handler.verify_image_checksum("/path/to/test/image.img")

    assert result is False


@patch("os.path.exists")
def test_verify_image_checksum_image_not_found(mock_exists, image_handler):
    """Test checksum verification with missing image file."""
    mock_exists.return_value = False

    with pytest.raises(ImageVerificationError) as exc_info:
        image_handler.verify_image_checksum("/path/to/nonexistent/image.img")

    assert "Image file not found" in str(exc_info.value)


@patch("os.path.exists")
def test_verify_image_checksum_checksum_not_found(mock_exists, image_handler):
    """Test checksum verification with missing checksum file."""
    mock_exists.side_effect = [True, False]  # Image exists, checksum does not

    with pytest.raises(ImageVerificationError) as exc_info:
        image_handler.verify_image_checksum("/path/to/test/image.img")

    assert "Checksum file not found" in str(exc_info.value)


@patch("os.path.exists")
def test_calculate_space_requirements(mock_exists, image_handler, sample_image_data):
    """Test space requirements calculation."""
    mock_exists.return_value = True

    image_handler.analyze_image = MagicMock(return_value=sample_image_data)

    result = image_handler.calculate_space_requirements("/path/to/test/image.img")

    assert "boot" in result
    assert "root" in result
    assert "total" in result
    assert "boot_human" in result
    assert "root_human" in result
    assert "total_human" in result

    assert result["boot"] > (256 * 1024 * 1024)
    assert result["root"] > (4.3 * 1024 * 1024 * 1024)
    assert result["total"] == result["boot"] + result["root"]


@patch("os.path.exists")
def test_calculate_space_requirements_error(mock_exists, image_handler):
    """Test space calculation with error in analyze_image."""
    mock_exists.return_value = True

    image_handler.analyze_image = MagicMock(
        side_effect=ImageHandlerError("Analysis failed")
    )

    with pytest.raises(ImageHandlerError) as exc_info:
        image_handler.calculate_space_requirements("/path/to/test/image.img")

    assert "Failed to calculate space requirements" in str(exc_info.value)


@patch("os.path.exists")
@patch("subprocess.run")
def test_extract_boot_partition_success(
    mock_run, mock_exists, image_handler, sample_image_data
):
    """Test successful boot partition extraction."""
    mock_exists.return_value = True

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_run.return_value = mock_process

    image_handler.analyze_image = MagicMock(return_value=sample_image_data)

    result = image_handler.extract_boot_partition(
        "/path/to/test/image.img", "/dev/mmcblk0p2"
    )

    assert result is True

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "dd" in args[0]
    assert "if=/path/to/test/image.img" in args
    assert "of=/dev/mmcblk0p2" in args


@patch("os.path.exists")
@patch("subprocess.run")
def test_extract_boot_partition_failure(
    mock_run, mock_exists, image_handler, sample_image_data
):
    """Test boot partition extraction with dd failure."""
    mock_exists.return_value = True

    image_handler.analyze_image = MagicMock(return_value=sample_image_data)

    mock_run.side_effect = Exception("dd failed")

    with pytest.raises(ImageExtractionError) as exc_info:
        image_handler.extract_boot_partition(
            "/path/to/test/image.img", "/dev/mmcblk0p2"
        )

    assert "Failed to extract boot partition" in str(exc_info.value)


@patch("os.path.exists")
@patch("subprocess.run")
def test_extract_root_partition_success(
    mock_run, mock_exists, image_handler, sample_image_data
):
    """Test successful root partition extraction."""
    mock_exists.return_value = True

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_run.return_value = mock_process

    image_handler.analyze_image = MagicMock(return_value=sample_image_data)

    result = image_handler.extract_root_partition(
        "/path/to/test/image.img", "/dev/mmcblk0p6"
    )

    assert result is True

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "dd" in args[0]
    assert "if=/path/to/test/image.img" in args
    assert "of=/dev/mmcblk0p6" in args


@patch("os.path.exists")
@patch("subprocess.run")
def test_extract_root_partition_failure(
    mock_run, mock_exists, image_handler, sample_image_data
):
    """Test root partition extraction with dd failure."""
    mock_exists.return_value = True

    image_handler.analyze_image = MagicMock(return_value=sample_image_data)

    mock_run.side_effect = Exception("dd failed")

    with pytest.raises(ImageExtractionError) as exc_info:
        image_handler.extract_root_partition(
            "/path/to/test/image.img", "/dev/mmcblk0p6"
        )

    assert "Failed to extract root partition" in str(exc_info.value)


@patch("subprocess.run")
def test_validate_extracted_partitions_success(mock_run, image_handler):
    """Test successful partition validation."""
    mock_partition_service = MagicMock()
    mock_partition_service.get_set_paths.return_value = {
        "boot": "/dev/mmcblk0p2",
        "root": "/dev/mmcblk0p6",
    }

    with patch(
        "wlanpi_core.services.partitions.partition_service.PartitionService",
        return_value=mock_partition_service,
    ):

        mock_process1 = MagicMock()
        mock_process1.returncode = 0
        mock_process2 = MagicMock()
        mock_process2.returncode = 0
        mock_run.side_effect = [mock_process1, mock_process2]

        result = image_handler.validate_extracted_partitions("B")

        assert result is True
        assert mock_run.call_count == 2


@patch("subprocess.run")
def test_validate_extracted_partitions_boot_failure(mock_run, image_handler):
    """Test partition validation with boot filesystem check failure."""
    mock_partition_service = MagicMock()
    mock_partition_service.get_set_paths.return_value = {
        "boot": "/dev/mmcblk0p2",
        "root": "/dev/mmcblk0p6",
    }

    with patch(
        "wlanpi_core.services.partitions.partition_service.PartitionService",
        return_value=mock_partition_service,
    ):

        mock_process1 = MagicMock()
        mock_process1.returncode = 2
        mock_process1.stderr = b"File system errors found"
        mock_run.return_value = mock_process1

        result = image_handler.validate_extracted_partitions("B")

        assert result is False


@patch("subprocess.run")
def test_validate_extracted_partitions_root_failure(mock_run, image_handler):
    """Test partition validation with root filesystem check failure."""
    mock_partition_service = MagicMock()
    mock_partition_service.get_set_paths.return_value = {
        "boot": "/dev/mmcblk0p2",
        "root": "/dev/mmcblk0p6",
    }

    with patch(
        "wlanpi_core.services.partitions.partition_service.PartitionService",
        return_value=mock_partition_service,
    ):

        mock_process1 = MagicMock()
        mock_process1.returncode = 0
        mock_process2 = MagicMock()
        mock_process2.returncode = 8
        mock_process2.stderr = b"File system errors found"
        mock_run.side_effect = [mock_process1, mock_process2]

        result = image_handler.validate_extracted_partitions("B")

        assert result is False


@patch("subprocess.run")
def test_validate_extracted_partitions_exception(mock_run, image_handler):
    """Test partition validation with unexpected exception."""
    mock_partition_service = MagicMock()
    mock_partition_service.get_set_paths.return_value = {
        "boot": "/dev/mmcblk0p2",
        "root": "/dev/mmcblk0p6",
    }

    with patch(
        "wlanpi_core.services.partitions.partition_service.PartitionService",
        return_value=mock_partition_service,
    ):

        mock_run.side_effect = Exception("Command failed")

        with pytest.raises(ImageVerificationError) as exc_info:
            image_handler.validate_extracted_partitions("B")

        assert "Failed to validate partitions" in str(exc_info.value)
