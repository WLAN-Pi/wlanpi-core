import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from wlanpi_core.core.logging import get_logger
from wlanpi_core.services.partitions.config_service import ConfigService
from wlanpi_core.services.partitions.image_handler import (
    ImageHandler,
    ImageHandlerError,
    ImageVerificationError,
)
from wlanpi_core.services.partitions.lock_service import LockService
from wlanpi_core.services.partitions.partition_service import PartitionService

log = get_logger(__name__)


class UpdateError(Exception):
    """Base exception for update-related errors."""

    pass


class UpdateManager:
    """Orchestrates the partition update process."""

    STATUS_IDLE = "idle"
    STATUS_PREPARING = "preparing"
    STATUS_UPDATING = "updating"
    STATUS_VERIFYING = "verifying"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    STEP_CHECK_PREREQUISITES = "check_prerequisites"
    STEP_VERIFY_IMAGE = "verify_image"
    STEP_PREPARE_PARTITIONS = "prepare_partitions"
    STEP_EXTRACT_BOOT = "extract_boot_partition"
    STEP_EXTRACT_ROOT = "extract_root_partition"
    STEP_VERIFY_EXTRACTED = "verify_extracted_partitions"
    STEP_UPDATE_CONFIG = "update_configuration"
    STEP_FINALIZE = "finalize_update"

    STATUS_DIR = "/home/shared/wlanpi-core/update_status"

    def __init__(
        self,
        lock_service: LockService,
        partition_service: PartitionService,
        config_service: ConfigService,
        image_handler: ImageHandler,
    ):
        """
        Initialize with required services.

        Args:
            lock_service: Service for managing update locks
            partition_service: Service for partition operations
            config_service: Service for configuration management
            image_handler: Service for image handling
        """
        self.lock_service = lock_service
        self.partition_service = partition_service
        self.config_service = config_service
        self.image_handler = image_handler

        os.makedirs(self.STATUS_DIR, exist_ok=True)

        self._status = self.STATUS_IDLE
        self._current_step = None
        self._progress = 0
        self._start_time = None
        self._end_time = None
        self._error = None
        self._target_set = None
        self._update_details = {}

        self._load_status()

    def _load_status(self) -> None:
        """Load update status from persistent storage if available."""
        status_file = os.path.join(self.STATUS_DIR, "update_status.json")
        if os.path.exists(status_file):
            try:
                with open(status_file, "r") as f:
                    status_data = json.load(f)

                self._status = status_data.get("status", self.STATUS_IDLE)
                self._current_step = status_data.get("current_step")
                self._progress = status_data.get("progress", 0)
                self._start_time = status_data.get("start_time")
                self._end_time = status_data.get("end_time")
                self._error = status_data.get("error")
                self._target_set = status_data.get("target_set")
                self._update_details = status_data.get("details", {})

                log.info(
                    f"Loaded update status: {self._status}, step: {self._current_step}"
                )
            except Exception as e:
                log.error(f"Failed to load update status: {str(e)}", exc_info=True)

    def _save_status(self) -> None:
        """Save current update status to persistent storage."""
        status_file = os.path.join(self.STATUS_DIR, "update_status.json")
        try:
            status_data = {
                "status": self._status,
                "current_step": self._current_step,
                "progress": self._progress,
                "start_time": self._start_time,
                "end_time": self._end_time,
                "error": self._error,
                "target_set": self._target_set,
                "details": self._update_details,
                "last_updated": datetime.now().isoformat(),
            }

            temp_file = f"{status_file}.tmp"
            with open(temp_file, "w") as f:
                json.dump(status_data, f, indent=2)

            os.rename(temp_file, status_file)

            if self._status in [self.STATUS_COMPLETED, self.STATUS_FAILED]:
                self._save_history_entry()

        except Exception as e:
            log.error(f"Failed to save update status: {str(e)}", exc_info=True)

    def _save_history_entry(self) -> None:
        """Save an entry to the update history file."""
        history_file = os.path.join(self.STATUS_DIR, "update_history.json")
        try:
            history = []
            if os.path.exists(history_file):
                try:
                    with open(history_file, "r") as f:
                        history = json.load(f)
                except:
                    history = []

            entry = {
                "id": len(history) + 1,
                "timestamp": datetime.now().isoformat(),
                "operation": "update",
                "status": self._status,
                "target_set": self._target_set,
                "start_time": self._start_time,
                "end_time": self._end_time,
                "duration": self._calculate_duration(),
                "error": self._error,
                "details": self._update_details,
            }

            history.append(entry)

            if len(history) > 100:
                history = history[-100:]

            temp_file = f"{history_file}.tmp"
            with open(temp_file, "w") as f:
                json.dump(history, f, indent=2)

            os.rename(temp_file, history_file)

        except Exception as e:
            log.error(f"Failed to save history entry: {str(e)}", exc_info=True)

    def _calculate_duration(self) -> Optional[float]:
        """Calculate update duration in seconds."""
        if self._start_time and self._end_time:
            try:
                start = datetime.fromisoformat(self._start_time)
                end = datetime.fromisoformat(self._end_time)
                return (end - start).total_seconds()
            except:
                pass
        return None

    def _update_progress(self, step: str, progress: int, message: str = None) -> None:
        """
        Update progress information and save status.

        Args:
            step: Current step identifier
            progress: Progress percentage (0-100)
            message: Optional status message
        """
        self._current_step = step
        self._progress = progress

        if message:
            self._update_details["last_message"] = message
            log.info(f"Update progress [{progress}%]: {message}")

        self._save_status()

    def prepare_update(self, image_path: str) -> Dict[str, Any]:
        """
        Validate prerequisites for update.

        Args:
            image_path: Path to the OS image file

        Returns:
            Dict with validation results

        Raises:
            UpdateError: If prerequisites check fails
        """
        try:
            if self._status in [
                self.STATUS_PREPARING,
                self.STATUS_UPDATING,
                self.STATUS_VERIFYING,
            ]:
                return {
                    "success": False,
                    "message": f"Update already in progress (status: {self._status})",
                    "details": self.get_update_status(),
                }

            self._status = self.STATUS_PREPARING
            self._current_step = self.STEP_CHECK_PREREQUISITES
            self._progress = 0
            self._start_time = datetime.now().isoformat()
            self._end_time = None
            self._error = None
            self._update_details = {
                "image_path": image_path,
                "hostname": os.uname().nodename,
            }
            self._save_status()

            if not os.path.exists(image_path):
                self._status = self.STATUS_FAILED
                self._error = f"Image file not found: {image_path}"
                self._save_status()
                raise UpdateError(self._error)

            self._update_progress(
                self.STEP_VERIFY_IMAGE, 10, "Verifying image checksums"
            )

            checksum_path = f"{image_path}.sha256"
            if os.path.exists(checksum_path):
                if not self.image_handler.verify_image_checksum(
                    image_path, checksum_path
                ):
                    self._status = self.STATUS_FAILED
                    self._error = "Image checksum verification failed"
                    self._save_status()
                    raise UpdateError(self._error)
            else:
                log.warning(
                    f"No checksum file found at {checksum_path}, skipping verification"
                )

            self._update_progress(
                self.STEP_VERIFY_IMAGE, 20, "Analyzing image structure"
            )
            image_info = self.image_handler.analyze_image(image_path)
            self._update_details["image_info"] = image_info

            self._update_progress(
                self.STEP_PREPARE_PARTITIONS, 30, "Identifying target partition set"
            )
            current_set = self.partition_service.get_current_partition_set()
            target_set = self.partition_service.get_inactive_partition_set()
            self._target_set = target_set

            target_paths = self.partition_service.get_set_paths(target_set)
            self._update_details["current_set"] = current_set
            self._update_details["target_set"] = target_set
            self._update_details["target_paths"] = target_paths

            self._update_progress(
                self.STEP_PREPARE_PARTITIONS, 40, "Calculating space requirements"
            )
            space_requirements = self.image_handler.calculate_space_requirements(
                image_path
            )
            self._update_details["space_requirements"] = space_requirements

            boot_available = self.partition_service.check_available_space(
                target_paths["boot"]
            )
            root_available = self.partition_service.check_available_space(
                target_paths["root"]
            )

            self._update_details["available_space"] = {
                "boot": boot_available,
                "boot_human": self._format_size(boot_available),
                "root": root_available,
                "root_human": self._format_size(root_available),
            }

            if boot_available < space_requirements["boot"]:
                self._status = self.STATUS_FAILED
                self._error = f"Insufficient space on boot partition: {self._format_size(boot_available)} available, {space_requirements['boot_human']} required"
                self._save_status()
                raise UpdateError(self._error)

            if root_available < space_requirements["root"]:
                self._status = self.STATUS_FAILED
                self._error = f"Insufficient space on root partition: {self._format_size(root_available)} available, {space_requirements['root_human']} required"
                self._save_status()
                raise UpdateError(self._error)

            partition_uuids = self.partition_service.get_partition_uuids()
            self._update_details["partition_uuids"] = partition_uuids

            self._update_progress(
                self.STEP_PREPARE_PARTITIONS,
                50,
                "Prerequisites check completed successfully",
            )

            return {
                "success": True,
                "message": "Prerequisites check completed successfully",
                "details": {
                    "current_set": current_set,
                    "target_set": target_set,
                    "target_paths": target_paths,
                    "space_requirements": space_requirements,
                    "available_space": self._update_details["available_space"],
                },
            }

        except UpdateError:
            raise
        except Exception as e:
            self._status = self.STATUS_FAILED
            self._error = str(e)
            self._save_status()
            log.error(f"Failed to prepare update: {str(e)}", exc_info=True)
            raise UpdateError(f"Failed to prepare update: {str(e)}")

    def execute_update(self, image_path: str) -> Dict[str, Any]:
        """
        Perform the actual update process.

        Args:
            image_path: Path to the OS image file

        Returns:
            Dict with update results

        Raises:
            UpdateError: If update fails
        """
        try:
            if self._status != self.STATUS_PREPARING:
                if self._status == self.STATUS_IDLE:
                    self.prepare_update(image_path)
                else:
                    return {
                        "success": False,
                        "message": f"Cannot execute update in current state: {self._status}",
                        "details": self.get_update_status(),
                    }

            self._status = self.STATUS_UPDATING
            self._save_status()

            target_set = self._target_set
            target_paths = self.partition_service.get_set_paths(target_set)
            partition_uuids = self.partition_service.get_partition_uuids()

            self._update_progress(
                self.STEP_EXTRACT_BOOT,
                60,
                f"Extracting boot partition to {target_paths['boot']}",
            )
            boot_success = self.image_handler.extract_boot_partition(
                image_path, target_paths["boot"]
            )

            self._update_progress(
                self.STEP_EXTRACT_ROOT,
                70,
                f"Extracting root partition to {target_paths['root']}",
            )
            root_success = self.image_handler.extract_root_partition(
                image_path, target_paths["root"]
            )

            self._update_progress(
                self.STEP_VERIFY_EXTRACTED, 80, "Verifying extracted partitions"
            )
            verify_success = self.image_handler.validate_extracted_partitions(
                target_set
            )

            if not verify_success:
                self._status = self.STATUS_FAILED
                self._error = "Partition verification failed after extraction"
                self._save_status()
                raise UpdateError(self._error)

            self._update_progress(
                self.STEP_UPDATE_CONFIG, 90, "Updating configuration files"
            )

            boot_uuid_key = f"boot{'1' if target_set == 'A' else '2'}"
            root_uuid_key = f"root{'1' if target_set == 'A' else '2'}"
            home_uuid_key = "home"

            root_uuid = partition_uuids.get(root_uuid_key)
            config_success = self.config_service.update_cmdline_txt(
                target_paths["boot"], root_uuid
            )

            home_uuid = partition_uuids.get(home_uuid_key)
            fstab_success = self.config_service.update_fstab(
                target_paths["root"], home_uuid
            )

            self._update_progress(
                self.STEP_FINALIZE, 100, "Update completed successfully"
            )
            self._status = self.STATUS_COMPLETED
            self._end_time = datetime.now().isoformat()
            self._save_status()

            return {
                "success": True,
                "message": "Update completed successfully",
                "details": {
                    "target_set": target_set,
                    "duration": self._calculate_duration(),
                    "next_steps": "Use tryboot-alternate-partition to test the new partition set",
                },
            }

        except UpdateError:
            raise
        except Exception as e:
            self._status = self.STATUS_FAILED
            self._error = str(e)
            self._end_time = datetime.now().isoformat()
            self._save_status()
            log.error(f"Failed to execute update: {str(e)}", exc_info=True)
            raise UpdateError(f"Failed to execute update: {str(e)}")

    def verify_update(self) -> Dict[str, Any]:
        """
        Verify update was successful by testing if system booted correctly.

        Returns:
            Dict with verification results
        """
        try:
            current_set = self.partition_service.get_current_partition_set()

            status = self.get_update_status()
            target_set = status.get("target_set")

            if current_set == target_set:
                verification_result = {
                    "success": True,
                    "message": f"Successfully booted into updated partition set {current_set}",
                    "details": {
                        "current_set": current_set,
                        "updated_set": target_set,
                        "boot_time": datetime.now().isoformat(),
                    },
                }

                self._status = self.STATUS_COMPLETED
                self._update_details["verification"] = verification_result
                self._save_status()

                return verification_result
            else:
                return {
                    "success": False,
                    "message": f"Not running on updated partition set. Current: {current_set}, Updated: {target_set}",
                    "details": {"current_set": current_set, "updated_set": target_set},
                }

        except Exception as e:
            log.error(f"Failed to verify update: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to verify update: {str(e)}",
                "error": str(e),
            }

    def get_update_status(self) -> Dict[str, Any]:
        """Return current update status with detailed information."""
        status = {
            "status": self._status,
            "current_step": self._current_step,
            "progress": self._progress,
            "target_set": self._target_set,
            "start_time": self._start_time,
            "end_time": self._end_time,
            "error": self._error,
            "duration": self._calculate_duration(),
            "details": self._update_details,
        }

        if (
            self._status in [self.STATUS_PREPARING, self.STATUS_UPDATING]
            and self._start_time
        ):
            try:
                if self._progress > 0:
                    start_time = datetime.fromisoformat(self._start_time)
                    elapsed = (datetime.now() - start_time).total_seconds()
                    total_estimated = elapsed * 100 / self._progress
                    remaining = total_estimated - elapsed

                    estimated_completion = datetime.now().timestamp() + remaining
                    status["estimated_completion"] = datetime.fromtimestamp(
                        estimated_completion
                    ).isoformat()
                    status["estimated_remaining_seconds"] = int(remaining)
            except:
                pass

        return status

    def get_update_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get history of previous updates.

        Args:
            limit: Maximum number of history entries to return

        Returns:
            List of update history entries
        """
        history_file = os.path.join(self.STATUS_DIR, "update_history.json")
        if not os.path.exists(history_file):
            return []

        try:
            with open(history_file, "r") as f:
                history = json.load(f)

            history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return history[:limit]

        except Exception as e:
            log.error(f"Failed to read update history: {str(e)}", exc_info=True)
            return []

    def rollback_update(self) -> Dict[str, Any]:
        """
        Revert to previous partition state.

        Returns:
            Dict with rollback results

        Raises:
            UpdateError: If rollback fails
        """
        try:
            current_set = self.partition_service.get_current_partition_set()
            rollback_set = "A" if current_set == "B" else "B"

            target_boot_num = 1 if rollback_set == "A" else 2

            tryboot_success = self.config_service.create_tryboot_txt(
                self.partition_service.BOOT1_PATH, target_boot_num
            )

            if not tryboot_success:
                raise UpdateError("Failed to create tryboot configuration for rollback")

            rollback_entry = {
                "timestamp": datetime.now().isoformat(),
                "operation": "rollback",
                "from_set": current_set,
                "to_set": rollback_set,
                "tryboot_configured": tryboot_success,
            }

            history_file = os.path.join(self.STATUS_DIR, "update_history.json")
            try:
                history = []
                if os.path.exists(history_file):
                    with open(history_file, "r") as f:
                        history = json.load(f)

                rollback_entry["id"] = len(history) + 1
                history.append(rollback_entry)

                temp_file = f"{history_file}.tmp"
                with open(temp_file, "w") as f:
                    json.dump(history, f, indent=2)

                os.rename(temp_file, history_file)

            except Exception as e:
                log.error(f"Failed to save rollback history: {str(e)}", exc_info=True)

            return {
                "success": True,
                "message": f"Rollback configuration created. System will boot into partition set {rollback_set} on next reboot.",
                "details": rollback_entry,
            }

        except Exception as e:
            log.error(f"Failed to rollback update: {str(e)}", exc_info=True)
            raise UpdateError(f"Failed to rollback update: {str(e)}")

    def _format_size(self, size_bytes: int) -> str:
        """Convert bytes to human-readable form."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024 or unit == "TB":
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024
