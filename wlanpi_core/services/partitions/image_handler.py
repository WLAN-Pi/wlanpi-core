import hashlib
import os
import subprocess
from typing import Dict, Optional

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class ImageHandlerError(Exception):
    """Base exception for image handling errors."""


class ImageVerificationError(ImageHandlerError):
    """Raised when image verification fails."""


class ImageExtractionError(ImageHandlerError):
    """Raised when image extraction fails."""


class ImageHandler:
    """Handles OS image operations for partition updates."""

    def __init__(self):
        """Initialize the image handler."""

    def analyze_image(self, image_path: str) -> Dict:
        """
        Analyze image structure and compatibility.

        Args:
            image_path: Path to the OS image file

        Returns:
            Dict containing image info including size, partitions, etc.

        Raises:
            ImageHandlerError: If image cannot be analyzed
        """
        if not os.path.exists(image_path):
            raise ImageHandlerError(f"Image file not found: {image_path}")

        try:
            image_size = os.path.getsize(image_path)

            result = subprocess.run(
                ["fdisk", "-l", image_path], capture_output=True, text=True, check=True
            )

            partitions = []
            lines = result.stdout.split("\n")
            for line in lines:
                if image_path in line and "sectors" in line:
                    continue
                if image_path in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        partitions.append(
                            {
                                "device": parts[0],
                                "start": int(parts[1]),
                                "end": int(parts[2]),
                                "sectors": int(parts[3]),
                                "size": parts[4],
                                "type": (
                                    " ".join(parts[5:]) if len(parts) > 5 else "Unknown"
                                ),
                            }
                        )

            return {
                "size": image_size,
                "size_human": self._format_size(image_size),
                "partitions": partitions,
                "partition_count": len(partitions),
            }

        except subprocess.CalledProcessError as e:
            log.error(f"Error analyzing image with fdisk: {e.stderr}")
            raise ImageHandlerError(f"Failed to analyze image: {str(e)}")
        except Exception as e:
            log.error(f"Error analyzing image: {str(e)}", exc_info=True)
            raise ImageHandlerError(f"Failed to analyze image: {str(e)}")

    def verify_image_checksum(
        self, image_path: str, checksum_path: Optional[str] = None
    ) -> bool:
        """
        Verify image integrity using SHA-256 checksum.

        Args:
            image_path: Path to the image file
            checksum_path: Optional path to checksum file, defaults to image_path + .sha256

        Returns:
            bool: True if checksum verification passes

        Raises:
            ImageVerificationError: If verification fails or checksum file is invalid
        """
        if not os.path.exists(image_path):
            raise ImageVerificationError(f"Image file not found: {image_path}")

        if not checksum_path:
            checksum_path = f"{image_path}.sha256"

        if not os.path.exists(checksum_path):
            raise ImageVerificationError(f"Checksum file not found: {checksum_path}")

        try:
            with open(checksum_path, "r") as f:
                expected_checksum = f.read().strip().split()[0]

            sha256_hash = hashlib.sha256()
            with open(image_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            actual_checksum = sha256_hash.hexdigest()

            if actual_checksum != expected_checksum:
                log.error(
                    f"Checksum verification failed: {actual_checksum} != {expected_checksum}"
                )
                return False

            return True

        except Exception as e:
            log.error(f"Error verifying checksum: {str(e)}", exc_info=True)
            raise ImageVerificationError(f"Failed to verify checksum: {str(e)}")

    def calculate_space_requirements(self, image_path: str) -> Dict[str, int]:
        """
        Calculate space needed for installation.

        Args:
            image_path: Path to the image file

        Returns:
            Dict with boot and root partition space requirements

        Raises:
            ImageHandlerError: If requirements cannot be calculated
        """
        try:
            image_info = self.analyze_image(image_path)

            boot_partition = None
            root_partition = None

            for i, partition in enumerate(image_info["partitions"]):
                if (
                    i == 0
                    or "boot" in partition["type"].lower()
                    or "vfat" in partition["type"].lower()
                ):
                    boot_partition = partition
                elif (
                    "root" in partition["type"].lower()
                    or "ext4" in partition["type"].lower()
                    or "linux" in partition["type"].lower()
                ):
                    root_partition = partition

            if not boot_partition and len(image_info["partitions"]) > 0:
                boot_partition = image_info["partitions"][0]

            if not root_partition and len(image_info["partitions"]) > 1:
                root_partition = image_info["partitions"][1]

            boot_size = (
                self._parse_size(boot_partition["size"]) if boot_partition else 0
            )
            root_size = (
                self._parse_size(root_partition["size"]) if root_partition else 0
            )

            boot_size = int(boot_size * 1.1)
            root_size = int(root_size * 1.1)

            return {
                "boot": boot_size,
                "root": root_size,
                "total": boot_size + root_size,
                "boot_human": self._format_size(boot_size),
                "root_human": self._format_size(root_size),
                "total_human": self._format_size(boot_size + root_size),
            }

        except Exception as e:
            log.error(f"Error calculating space requirements: {str(e)}", exc_info=True)
            raise ImageHandlerError(f"Failed to calculate space requirements: {str(e)}")

    def extract_boot_partition(self, image_path: str, target_device: str) -> bool:
        """
        Extract and write boot partition from image.

        Args:
            image_path: Path to the image file
            target_device: Target device to write to (e.g., /dev/mmcblk0p2)

        Returns:
            bool: True if extraction was successful

        Raises:
            ImageExtractionError: If extraction fails
        """
        try:
            image_info = self.analyze_image(image_path)

            boot_partition = None
            for i, partition in enumerate(image_info["partitions"]):
                if (
                    i == 0
                    or "boot" in partition["type"].lower()
                    or "vfat" in partition["type"].lower()
                ):
                    boot_partition = partition
                    break

            if not boot_partition:
                raise ImageExtractionError("Could not identify boot partition in image")

            # Calculate offset and size
            sector_size = 512  # Default sector size
            boot_partition["start"] * sector_size
            count = boot_partition["sectors"]

            cmd = [
                "dd",
                f"if={image_path}",
                f"of={target_device}",
                f"bs={sector_size}",
                f"skip={boot_partition['start']}",
                f"count={count}",
                "conv=fsync",
            ]

            log.info(f"Extracting boot partition: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)

            return True

        except subprocess.CalledProcessError as e:
            log.error(f"Error extracting boot partition: {e}", exc_info=True)
            raise ImageExtractionError(f"Failed to extract boot partition: {str(e)}")
        except Exception as e:
            log.error(f"Error extracting boot partition: {str(e)}", exc_info=True)
            raise ImageExtractionError(f"Failed to extract boot partition: {str(e)}")

    def extract_root_partition(self, image_path: str, target_device: str) -> bool:
        """
        Extract and write root partition from image.

        Args:
            image_path: Path to the image file
            target_device: Target device to write to (e.g., /dev/mmcblk0p6)

        Returns:
            bool: True if extraction was successful

        Raises:
            ImageExtractionError: If extraction fails
        """
        try:
            image_info = self.analyze_image(image_path)

            root_partition = None
            for i, partition in enumerate(image_info["partitions"]):
                if i > 0 and (
                    "root" in partition["type"].lower()
                    or "ext4" in partition["type"].lower()
                    or "linux" in partition["type"].lower()
                ):
                    root_partition = partition
                    break

            if not root_partition:
                if len(image_info["partitions"]) > 1:
                    root_partition = image_info["partitions"][1]
                else:
                    raise ImageExtractionError(
                        "Could not identify root partition in image"
                    )

            sector_size = 512  # Default sector size
            root_partition["start"] * sector_size
            count = root_partition["sectors"]

            # Use dd to extract and write partition
            cmd = [
                "dd",
                f"if={image_path}",
                f"of={target_device}",
                f"bs={sector_size}",
                f"skip={root_partition['start']}",
                f"count={count}",
                "conv=fsync",
            ]

            log.info(f"Extracting root partition: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)

            return True

        except subprocess.CalledProcessError as e:
            log.error(f"Error extracting root partition: {e}", exc_info=True)
            raise ImageExtractionError(f"Failed to extract root partition: {str(e)}")
        except Exception as e:
            log.error(f"Error extracting root partition: {str(e)}", exc_info=True)
            raise ImageExtractionError(f"Failed to extract root partition: {str(e)}")

    def validate_extracted_partitions(self, target_set: str) -> bool:
        """
        Verify partitions were written correctly.

        Args:
            target_set: Target partition set ("A" or "B")

        Returns:
            bool: True if validation passes

        Raises:
            ImageVerificationError: If validation fails
        """
        try:
            from wlanpi_core.services.partitions.partition_service import (
                PartitionService,
            )

            partition_service = PartitionService()
            set_paths = partition_service.get_set_paths(target_set)

            boot_device = set_paths["boot"]
            root_device = set_paths["root"]

            log.info(f"Validating boot partition: {boot_device}")
            result = subprocess.run(
                ["fsck.vfat", "-n", boot_device], capture_output=True, check=False
            )

            if result.returncode != 0:
                log.error(f"Boot partition validation failed: {result.stderr.decode()}")
                return False

            log.info(f"Validating root partition: {root_device}")
            result = subprocess.run(
                ["e2fsck", "-n", "-f", root_device], capture_output=True, check=False
            )

            # e2fsck returns 0 if no errors, 1 if errors fixed, 2+ for issues
            if result.returncode > 1:
                log.error(f"Root partition validation failed: {result.stderr.decode()}")
                return False

            return True

        except Exception as e:
            log.error(f"Error validating extracted partitions: {str(e)}", exc_info=True)
            raise ImageVerificationError(f"Failed to validate partitions: {str(e)}")

    def _format_size(self, size_bytes: int) -> str:
        """Convert bytes to human-readable form."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024 or unit == "TB":
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024

    def _parse_size(self, size_str: str) -> int:
        """Parse human-readable size string to bytes."""
        size_str = size_str.upper()
        if "K" in size_str:
            return int(float(size_str.replace("K", "")) * 1024)
        elif "M" in size_str:
            return int(float(size_str.replace("M", "")) * 1024 * 1024)
        elif "G" in size_str:
            return int(float(size_str.replace("G", "")) * 1024 * 1024 * 1024)
        else:
            return int(float(size_str))
