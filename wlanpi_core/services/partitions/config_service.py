import os
import re
import shutil
import tempfile
from typing import Dict, Optional, Union, Any

from wlanpi_core.core.logging import get_logger
from wlanpi_core.services.partitions.device_service import DeviceService
from wlanpi_core.services.partitions.partition_service import PartitionService
from wlanpi_core.utils.general import run_command

log = get_logger(__name__)


class ConfigService:
    """
    Service for managing boot configuration files on A/B partition systems.

    This service handles:
    - Updating cmdline.txt files
    - Managing tryboot configuration
    - Setting default boot partitions
    - Backing up and restoring configuration files
    """

    BACKUP_DIR = "/home/share/wlanpi-core/config_backups"

    def __init__(self):
        """Initialize the config service."""
        self.device_service = DeviceService()
        self.partition_service = PartitionService()
        self._validate_device()
        self._ensure_backup_dir()

    def _validate_device(self) -> None:
        """
        Validate that this is running on a compatible device.
        Raises an exception if not a compatible device.
        """
        if not self.device_service.is_allowed_device():
            error_msg = (
                self.device_service.get_compatibility_error()
                or "Unknown device compatibility error"
            )
            log.error(f"Device validation failed: {error_msg}")
            raise ValueError(
                f"Partition management not supported on this device: {error_msg}"
            )

    def _ensure_backup_dir(self) -> None:
        """
        Ensure the backup directory for configuration files exists.
        """
        os.makedirs(self.BACKUP_DIR, mode=0o755, exist_ok=True)

    def backup_config(self, filename: str) -> str:
        """
        Create a backup of a configuration file.

        Args:
            filename: Path to the file to backup

        Returns:
            str: Path to the backup file or empty string if backup failed
        """
        if not os.path.exists(filename):
            log.error(f"Cannot backup non-existent file: {filename}")
            return ""

        try:
            backup_filename = os.path.join(
                self.BACKUP_DIR, f"{os.path.basename(filename)}.bak"
            )
            shutil.copy2(filename, backup_filename)
            log.info(f"Backed up {filename} to {backup_filename}")
            return backup_filename
        except Exception as e:
            log.error(f"Failed to back up {filename}: {e}", exc_info=True)
            return ""

    def restore_config(self, filename: str) -> bool:
        """
        Restore a configuration file from backup.

        Args:
            filename: Path to the original file

        Returns:
            bool: True if restoration succeeded, False otherwise
        """
        backup_filename = os.path.join(
            self.BACKUP_DIR, f"{os.path.basename(filename)}.bak"
        )
        if not os.path.exists(backup_filename):
            log.error(f"Backup file does not exist: {backup_filename}")
            return False

        try:
            shutil.copy2(backup_filename, filename)
            log.info(f"Restored {filename} from {backup_filename}")
            return True
        except Exception as e:
            log.error(f"Failed to restore {filename}: {e}", exc_info=True)
            return False

    def update_cmdline_txt(
        self, boot_partition: str, root_uuid: str, create_backup: bool = True
    ) -> bool:
        """
        Update cmdline.txt with the correct root partition UUID.

        Args:
            boot_partition: Path to the boot partition
            root_uuid: PARTUUID of the root partition to boot from
            create_backup: Whether to create a backup before updating

        Returns:
            bool: True if successful, False otherwise
        """

        temp_dir = None
        need_mount = not self.partition_service.is_mounted(boot_partition)

        try:
            mount_point = "/boot"

            if need_mount:
                temp_dir = tempfile.mkdtemp()
                mount_point = temp_dir
                if not self.partition_service.mount_partition(
                    boot_partition, mount_point
                ):
                    log.error(
                        f"Failed to mount {boot_partition} for cmdline.txt update"
                    )
                    return False

            cmdline_path = os.path.join(mount_point, "cmdline.txt")

            if not os.path.exists(cmdline_path):
                log.error(f"cmdline.txt not found at {cmdline_path}")
                return False

            if create_backup:
                self.backup_config(cmdline_path)

            with open(cmdline_path, "r") as f:
                cmdline = f.read().strip()

            new_cmdline = re.sub(
                r"root=PARTUUID=[a-fA-F0-9\-]+", f"root=PARTUUID={root_uuid}", cmdline
            )

            with open(cmdline_path, "w") as f:
                f.write(new_cmdline)

            log.info(
                f"Updated cmdline.txt at {cmdline_path} with root=PARTUUID={root_uuid}"
            )

            return True

        except Exception as e:
            log.error(f"Error updating cmdline.txt: {e}", exc_info=True)
            return False

        finally:
            if need_mount and temp_dir:
                self.partition_service.unmount_partition(temp_dir)
                try:
                    os.rmdir(temp_dir)
                except:
                    pass

    def create_tryboot_txt(self, boot_partition: str, target_boot_num: int) -> bool:
        """
        Create a tryboot.txt file to enable one-time boot from a specific partition.

        Args:
            boot_partition: Path to the boot partition where tryboot.txt should be created
            target_boot_num: Boot partition number to try (1 or 2)

        Returns:
            bool: True if successful, False otherwise
        """
        if target_boot_num not in [1, 2]:
            log.error(f"Invalid target boot partition number: {target_boot_num}")
            return False

        temp_dir = None
        need_mount = not self.partition_service.is_mounted(boot_partition)

        try:
            mount_point = "/boot"

            if need_mount:
                temp_dir = tempfile.mkdtemp()
                mount_point = temp_dir
                if not self.partition_service.mount_partition(
                    boot_partition, mount_point
                ):
                    log.error(
                        f"Failed to mount {boot_partition} for tryboot.txt creation"
                    )
                    return False

            tryboot_path = os.path.join(mount_point, "tryboot.txt")

            with open(tryboot_path, "w") as f:
                f.write(f"boot_partition={target_boot_num}\n")

            log.info(
                f"Created tryboot.txt at {tryboot_path} with boot_partition={target_boot_num}"
            )

            return True

        except Exception as e:
            log.error(f"Error creating tryboot.txt: {e}", exc_info=True)
            return False

        finally:
            if need_mount and temp_dir:
                self.partition_service.unmount_partition(temp_dir)
                try:
                    os.rmdir(temp_dir)
                except:
                    pass

    def update_autoboot_txt(
        self, boot_partition: str, target_boot_num: int, create_backup: bool = True
    ) -> bool:
        """
        Update autoboot.txt to set the default boot partition.

        Args:
            boot_partition: Path to the boot partition containing autoboot.txt
            target_boot_num: Boot partition number to set as default (1 or 2)
            create_backup: Whether to create a backup before updating

        Returns:
            bool: True if successful, False otherwise
        """
        if target_boot_num not in [1, 2]:
            log.error(f"Invalid target boot partition number: {target_boot_num}")
            return False

        temp_dir = None
        need_mount = not self.partition_service.is_mounted(boot_partition)

        try:
            mount_point = "/boot"

            if need_mount:
                temp_dir = tempfile.mkdtemp()
                mount_point = temp_dir
                if not self.partition_service.mount_partition(
                    boot_partition, mount_point
                ):
                    log.error(
                        f"Failed to mount {boot_partition} for autoboot.txt update"
                    )
                    return False

            autoboot_path = os.path.join(mount_point, "autoboot.txt")

            if os.path.exists(autoboot_path) and create_backup:
                self.backup_config(autoboot_path)

            current_autoboot = ""
            if os.path.exists(autoboot_path):
                with open(autoboot_path, "r") as f:
                    current_autoboot = f.read()

            if re.search(r"boot_partition=\d+", current_autoboot):
                new_autoboot = re.sub(
                    r"boot_partition=\d+",
                    f"boot_partition={target_boot_num}",
                    current_autoboot,
                )
            else:
                new_autoboot = f"boot_partition={target_boot_num}\n"

            with open(autoboot_path, "w") as f:
                f.write(new_autoboot)

            log.info(
                f"Updated autoboot.txt at {autoboot_path} with boot_partition={target_boot_num}"
            )

            return True

        except Exception as e:
            log.error(f"Error updating autoboot.txt: {e}", exc_info=True)
            return False

        finally:
            if need_mount and temp_dir:
                self.partition_service.unmount_partition(temp_dir)
                try:
                    os.rmdir(temp_dir)
                except:
                    pass

    def update_fstab(
        self,
        root_partition: str,
        home_uuid: Optional[str] = None,
        create_backup: bool = True,
    ) -> bool:
        """
        Update fstab on a root partition to use the correct UUIDs.

        Args:
            root_partition: Path to the root partition
            home_uuid: Optional PARTUUID of the home partition
            create_backup: Whether to create a backup before updating

        Returns:
            bool: True if successful, False otherwise
        """
        temp_dir = None
        need_mount = not self.partition_service.is_mounted(root_partition)

        try:
            mount_point = "/"

            if need_mount:
                temp_dir = tempfile.mkdtemp()
                mount_point = temp_dir
                if not self.partition_service.mount_partition(
                    root_partition, mount_point
                ):
                    log.error(f"Failed to mount {root_partition} for fstab update")
                    return False

            fstab_path = os.path.join(mount_point, "etc", "fstab")

            if not os.path.exists(fstab_path):
                log.error(f"fstab not found at {fstab_path}")
                return False

            if create_backup:
                self.backup_config(fstab_path)

            with open(fstab_path, "r") as f:
                fstab_content = f.read()

            if home_uuid:
                new_fstab = re.sub(
                    r"PARTUUID=[a-fA-F0-9\-]+\s+/home",
                    f"PARTUUID={home_uuid} /home",
                    fstab_content,
                )

                with open(fstab_path, "w") as f:
                    f.write(new_fstab)

                log.info(
                    f"Updated fstab at {fstab_path} with home PARTUUID={home_uuid}"
                )

            return True

        except Exception as e:
            log.error(f"Error updating fstab: {e}", exc_info=True)
            return False

        finally:
            if need_mount and temp_dir:
                self.partition_service.unmount_partition(temp_dir)
                try:
                    os.rmdir(temp_dir)
                except:
                    pass

    def tryboot_alternate_partition(self) -> bool:
        """
        Configure the system to boot once from the alternate partition.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            current_set = self.partition_service.get_current_partition_set()

            if current_set not in ["A", "B"]:
                log.error(f"Cannot determine alternate partition from '{current_set}'")
                return False

            target_boot_num = 2 if current_set == "A" else 1

            boot_result = run_command(
                "findmnt -n -o SOURCE /boot", shell=True, suppress_warning=True
            )
            current_boot = boot_result.stdout.strip()

            if not self.create_tryboot_txt(current_boot, target_boot_num):
                log.error("Failed to create tryboot.txt")
                return False

            log.info(
                f"System configured to try boot from partition set {'B' if current_set == 'A' else 'A'}"
            )

            return True

        except Exception as e:
            log.error(f"Error configuring tryboot: {e}", exc_info=True)
            return False

    def commit_current_partition(self) -> bool:
        """
        Make the current partition set the default boot option.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            current_set = self.partition_service.get_current_partition_set()

            if current_set not in ["A", "B"]:
                log.error(
                    f"Cannot commit mixed or unknown partition set: {current_set}"
                )
                return False

            self.partition_service.get_partition_uuids()

            target_boot_num = 1 if current_set == "A" else 2

            boot1_path = self.partition_service.BOOT1_PATH

            if not self.update_autoboot_txt(boot1_path, target_boot_num):
                log.error("Failed to update autoboot.txt")
                return False

            log.info(
                f"Committed partition set {current_set} as the default boot option"
            )

            return True

        except Exception as e:
            log.error(f"Error committing current partition: {e}", exc_info=True)
            return False

    def prepare_partition_update(
        self, target_set: str, source_set: Optional[str] = None
    ) -> Dict[str, Union[str, bool]]:
        """
        Prepare configuration for updating a partition set.

        Args:
            target_set: The partition set to update ("A" or "B")
            source_set: Optional source set to copy configuration from

        Returns:
            Dict with status and configuration details
        """
        try:
            if target_set not in ["A", "B"]:
                return {
                    "success": False,
                    "error": f"Invalid target partition set: {target_set}",
                }

            if not source_set:
                source_set = self.partition_service.get_current_partition_set()
                if source_set not in ["A", "B"]:
                    return {
                        "success": False,
                        "error": f"Cannot use {source_set} as source partition set",
                    }

            target_paths = self.partition_service.get_set_paths(target_set)
            self.partition_service.get_set_paths(source_set)

            partition_uuids = self.partition_service.get_partition_uuids()

            for name, path in target_paths.items():
                if not os.path.exists(path):
                    return {
                        "success": False,
                        "error": f"Target {name} partition {path} does not exist",
                    }

            config_info = {
                "success": True,
                "target_set": target_set,
                "source_set": source_set,
                "target_boot": target_paths["boot"],
                "target_root": target_paths["root"],
                "target_boot_uuid": partition_uuids.get(
                    f"boot{'1' if target_set == 'A' else '2'}", ""
                ),
                "target_root_uuid": partition_uuids.get(
                    f"root{'1' if target_set == 'A' else '2'}", ""
                ),
                "home_uuid": partition_uuids.get("home", ""),
            }

            return config_info

        except Exception as e:
            log.error(f"Error preparing partition update: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def get_boot_history(self) -> Dict[str, Any]:
        """
        Get information about recent boot attempts.

        Returns:
            Dict containing boot history information
        """
        try:
            boot_history_result = run_command(
                "journalctl --list-boots | head -10",
                shell=True,
                raise_on_fail=False,
                suppress_warning=True,
            )

            boot_entries = []
            if boot_history_result.success:
                lines = boot_history_result.stdout.strip().split("\n")
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 4:
                        boot_id = parts[0]
                        boot_time = " ".join(parts[1:])
                        boot_entries.append({"id": boot_id, "time": boot_time})

            has_failed_boots = any(
                entry["id"].startswith("-") for entry in boot_entries
            )

            current_set = self.partition_service.get_current_partition_set()

            kernel_result = run_command("uname -r", shell=True, suppress_warning=True)
            kernel_version = (
                kernel_result.stdout.strip() if kernel_result.success else "Unknown"
            )

            return {
                "boot_entries": boot_entries,
                "has_failed_boots": has_failed_boots,
                "current_kernel": kernel_version,
                "current_set": current_set,
            }

        except Exception as e:
            log.error(f"Error getting boot history: {e}", exc_info=True)
            return {"error": str(e)}
