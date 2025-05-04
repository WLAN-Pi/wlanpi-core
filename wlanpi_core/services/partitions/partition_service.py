import os
import re
import tempfile
from typing import Any, Dict

from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.services.partitions.device_service import DeviceService
from wlanpi_core.utils.general import run_command

log = get_logger(__name__)


class PartitionService:
    """
    Core service for partition management operations on WLAN Pi Go devices.

    This service handles:
    - Detecting current partition set (A or B)
    - Identifying inactive partition for updates
    - Safely mounting and unmounting partitions
    - Getting PARTUUID values for configuration updates
    - Validating partition structure and integrity
    """

    PARTITION_SET_A = "A"
    PARTITION_SET_B = "B"

    BOOT1_PATH = "/dev/mmcblk0p1"  # BOOT1FS/p1 (Set A)
    ROOT1_PATH = "/dev/mmcblk0p5"  # ROOT1FS/p5 (Set A)

    BOOT2_PATH = "/dev/mmcblk0p2"  # BOOT2FS/p2 (Set B)
    ROOT2_PATH = "/dev/mmcblk0p6"  # ROOT2FS/p6 (Set B)
    HOME_PATH = "/dev/mmcblk0p7"  # HOME partition (persistent)

    BOOT_MOUNT = "/boot"
    ROOT_MOUNT = "/mnt/root"

    def __init__(self):
        """Initialize the partition service."""
        self.device_service = DeviceService()
        self._validate_device()
        self._current_set = self._detect_current_set()

    def _validate_device(self) -> None:
        """
        Validate that this is running on a compatible device.
        Raises an exception if not a compatible device.
        """
        if not self.device_service.is_go_device():
            error_msg = (
                self.device_service.get_compatibility_error()
                or "Unknown device compatibility error"
            )
            log.error(f"Device validation failed: {error_msg}")
            raise ValueError(
                f"Partition management not supported on this device: {error_msg}"
            )

    def _detect_current_set(self) -> str:
        """
        Detect which partition set (A or B) is currently active.

        Returns:
            str: "A" or "B" indicating the active partition set
        """
        try:
            result = run_command(
                "findmnt -n -o SOURCE /", shell=True, suppress_warning=True
            )
            current_root = result.stdout.strip()

            boot_result = run_command(
                "findmnt -n -o SOURCE /boot", shell=True, suppress_warning=True
            )
            current_boot = boot_result.stdout.strip()

            log.debug(f"Current root partition: {current_root}")
            log.debug(f"Current boot partition: {current_boot}")

            if self.ROOT1_PATH in current_root and self.BOOT1_PATH in current_boot:
                return self.PARTITION_SET_A
            elif self.ROOT2_PATH in current_root and self.BOOT2_PATH in current_boot:
                return self.PARTITION_SET_B
            else:
                log.warning(
                    f"Mixed partition usage detected: boot={current_boot}, root={current_root}"
                )
                if self.ROOT1_PATH in current_root:
                    return f"Mixed (root A)"
                elif self.ROOT2_PATH in current_root:
                    return f"Mixed (root B)"
                else:
                    log.error(
                        f"Unknown partition configuration: boot={current_boot}, root={current_root}"
                    )
                    return "Unknown"

        except RunCommandError as e:
            log.error(f"Error detecting current partition set: {e}", exc_info=True)
            return "Unknown"

    def get_current_partition_set(self) -> str:
        """
        Get the currently active partition set.

        Returns:
            str: "A" or "B" indicating which set is active
        """
        return self._current_set

    def get_inactive_partition_set(self) -> str:
        """
        Get the inactive partition set (the one not currently booted).

        Returns:
            str: "A" or "B" indicating which set is inactive
        """
        if self._current_set == self.PARTITION_SET_A:
            return self.PARTITION_SET_B
        elif self._current_set == self.PARTITION_SET_B:
            return self.PARTITION_SET_A
        else:
            try:
                result = run_command("findmnt -n -o SOURCE /", shell=True)
                current_root = result.stdout.strip()

                if self.ROOT1_PATH in current_root:
                    return self.PARTITION_SET_B
                elif self.ROOT2_PATH in current_root:
                    return self.PARTITION_SET_A
                else:
                    log.warning(
                        f"Cannot determine inactive partition set, defaulting to B"
                    )
                    return self.PARTITION_SET_B
            except Exception as e:
                log.error(
                    f"Error determining inactive partition set: {e}", exc_info=True
                )
                return self.PARTITION_SET_B

    def get_device_paths(self) -> Dict[str, str]:
        """
        Get the device paths for all relevant partitions.

        Returns:
            Dict[str, str]: Dictionary mapping partition names to device paths
        """
        return {
            "boot1": self.BOOT1_PATH,
            "boot2": self.BOOT2_PATH,
            "root1": self.ROOT1_PATH,
            "root2": self.ROOT2_PATH,
            "home": self.HOME_PATH,
        }

    def get_set_paths(self, partition_set: str) -> Dict[str, str]:
        """
        Get the device paths for a specific partition set.

        Args:
            partition_set: "A" or "B" indicating which set to get

        Returns:
            Dict[str, str]: Dictionary with "boot" and "root" paths
        """
        if partition_set == self.PARTITION_SET_A:
            return {"boot": self.BOOT1_PATH, "root": self.ROOT1_PATH}
        elif partition_set == self.PARTITION_SET_B:
            return {"boot": self.BOOT2_PATH, "root": self.ROOT2_PATH}
        else:
            raise ValueError(f"Invalid partition set: {partition_set}")

    def get_partition_uuids(self) -> Dict[str, str]:
        """
        Get PARTUUIDs for all partitions.

        Returns:
            Dict[str, str]: Dictionary mapping partition names to PARTUUIDs
        """
        try:
            result = run_command("blkid", shell=True, suppress_warning=True)
            output = result.stdout.strip()

            partitions = {}

            for line in output.split("\n"):
                for part_name, part_path in self.get_device_paths().items():
                    if part_path in line:
                        partuuid_match = re.search(r'PARTUUID="([^"]+)"', line)
                        if partuuid_match:
                            partitions[part_name] = partuuid_match.group(1)

            return partitions

        except RunCommandError as e:
            log.error(f"Error getting partition UUIDs: {e}", exc_info=True)
            return {}

    def get_partition_usage(self) -> Dict[str, Dict[str, Any]]:
        """
        Get usage statistics for all partitions.

        Returns:
            Dict containing usage data for each partition
        """
        usage = {}

        try:
            df_result = run_command("df -h", shell=True, suppress_warning=True)
            df_output = df_result.stdout.strip()

            for path_name, path in self.get_device_paths().items():
                for line in df_output.split("\n"):
                    if path in line:
                        parts = line.split()
                        if len(parts) >= 6:
                            usage[path_name] = {
                                "size": parts[1],
                                "used": parts[2],
                                "available": parts[3],
                                "percent_used": parts[4],
                                "mount_point": (
                                    parts[5] if len(parts) > 5 else "Not mounted"
                                ),
                            }

            return usage

        except RunCommandError as e:
            log.error(f"Error getting partition usage: {e}", exc_info=True)
            return {}

    def get_boot_info(self) -> Dict[str, Any]:
        """
        Get comprehensive boot information, based on the boot-info bash script.

        Returns:
            Dict containing detailed boot configuration information
        """
        info = {}

        try:
            uname_result = run_command("uname -a", shell=True, suppress_warning=True)
            info["system_info"] = uname_result.stdout.strip()

            try:
                with open("/proc/device-tree/model", "r") as f:
                    info["model"] = f.read().strip()
            except:
                info["model"] = "Unknown"

            boot_result = run_command(
                "findmnt -n -o SOURCE /boot", shell=True, suppress_warning=True
            )
            root_result = run_command(
                "findmnt -n -o SOURCE /", shell=True, suppress_warning=True
            )
            home_result = run_command(
                "findmnt -n -o SOURCE /home",
                shell=True,
                raise_on_fail=False,
                suppress_warning=True,
            )

            info["current_boot_dev"] = boot_result.stdout.strip()
            info["current_root_dev"] = root_result.stdout.strip()
            info["current_home_dev"] = (
                home_result.stdout.strip() if home_result.success else "Unknown"
            )

            if (
                info["current_boot_dev"] == self.BOOT1_PATH
                and info["current_root_dev"] == self.ROOT1_PATH
            ):
                info["current_set"] = "A"
            elif (
                info["current_boot_dev"] == self.BOOT2_PATH
                and info["current_root_dev"] == self.ROOT2_PATH
            ):
                info["current_set"] = "B"
            else:
                info["current_set"] = "Mixed"
                if info["current_boot_dev"] == self.BOOT1_PATH:
                    info["current_set"] = "Mixed (boot A)"
                elif info["current_boot_dev"] == self.BOOT2_PATH:
                    info["current_set"] = "Mixed (boot B)"

            try:
                with open("/boot/cmdline.txt", "r") as f:
                    info["cmdline_txt"] = f.read().strip()
            except:
                info["cmdline_txt"] = "Not found"

            try:
                if os.path.exists("/boot/cmdline-b.txt"):
                    with open("/boot/cmdline-b.txt", "r") as f:
                        info["cmdline_b_txt"] = f.read().strip()
                else:
                    info["cmdline_b_txt"] = "File does not exist"
            except:
                info["cmdline_b_txt"] = "Error reading file"

            try:
                if os.path.exists("/boot/tryboot.txt"):
                    with open("/boot/tryboot.txt", "r") as f:
                        info["tryboot_txt"] = f.read().strip()
                else:
                    info["tryboot_txt"] = "File does not exist"
            except:
                info["tryboot_txt"] = "Error reading file"

            try:
                if os.path.exists("/boot/autoboot.txt"):
                    with open("/boot/autoboot.txt", "r") as f:
                        info["autoboot_txt"] = f.read().strip()
                        boot_part_match = re.search(
                            r"boot_partition=(\d+)", info["autoboot_txt"]
                        )
                        if boot_part_match:
                            info["current_autoboot_partition"] = boot_part_match.group(
                                1
                            )
                        else:
                            info["current_autoboot_partition"] = "Not specified"
                else:
                    info["autoboot_txt"] = "File does not exist"
                    info["current_autoboot_partition"] = "Not specified"
            except:
                info["autoboot_txt"] = "Error reading file"
                info["current_autoboot_partition"] = "Unknown"

            if info["current_boot_dev"] != self.BOOT1_PATH:
                temp_dir = tempfile.mkdtemp()
                try:
                    if run_command(
                        f"mount {self.BOOT1_PATH} {temp_dir}",
                        shell=True,
                        raise_on_fail=False,
                        suppress_warning=True,
                    ).success:
                        autoboot_path = os.path.join(temp_dir, "autoboot.txt")
                        if os.path.exists(autoboot_path):
                            with open(autoboot_path, "r") as f:
                                info["boot1_autoboot_txt"] = f.read().strip()
                                boot_part_match = re.search(
                                    r"boot_partition=(\d+)", info["boot1_autoboot_txt"]
                                )
                                if boot_part_match:
                                    info["boot1_partition"] = boot_part_match.group(1)
                                else:
                                    info["boot1_partition"] = "Not specified"
                        else:
                            info["boot1_autoboot_txt"] = "File does not exist"
                            info["boot1_partition"] = "None"

                        run_command(
                            f"umount {temp_dir}",
                            shell=True,
                            raise_on_fail=False,
                            suppress_warning=True,
                        )
                    else:
                        info["boot1_autoboot_txt"] = "Failed to mount boot partition 1"
                        info["boot1_partition"] = "Unknown"
                finally:
                    os.rmdir(temp_dir)
            else:
                info["boot1_autoboot_txt"] = info.get("autoboot_txt", "Unknown")
                info["boot1_partition"] = info.get(
                    "current_autoboot_partition", "Unknown"
                )

            if info.get("boot1_partition") == "1":
                info["power_loss_boot"] = "A"
            elif info.get("boot1_partition") == "2":
                info["power_loss_boot"] = "B"
            elif info.get("boot1_partition") == "None":
                info["power_loss_boot"] = "A (default)"
            else:
                info["power_loss_boot"] = "Unknown"

            lsblk_result = run_command(
                "lsblk -o NAME,SIZE,MOUNTPOINT,FSTYPE,LABEL,UUID,PARTUUID",
                shell=True,
                suppress_warning=True,
            )
            info["partition_layout"] = lsblk_result.stdout.strip()

            df_result = run_command(
                "df -h | grep mmcblk0",
                shell=True,
                raise_on_fail=False,
                suppress_warning=True,
            )
            info["partition_usage"] = (
                df_result.stdout.strip() if df_result.success else "Not available"
            )

            cmdline_result = run_command(
                "cat /proc/cmdline", shell=True, suppress_warning=True
            )
            info["kernel_cmdline"] = cmdline_result.stdout.strip()

            boot_history_result = run_command(
                "journalctl --list-boots | head -5",
                shell=True,
                raise_on_fail=False,
                suppress_warning=True,
            )
            info["boot_history"] = (
                boot_history_result.stdout.strip()
                if boot_history_result.success
                else "Not available"
            )

            return info

        except Exception as e:
            log.error(f"Error getting boot information: {e}", exc_info=True)
            return {"error": str(e)}

    def mount_partition(self, device: str, mount_point: str) -> bool:
        """
        Safely mount a partition.

        Args:
            device: Device path to mount
            mount_point: Directory to mount to

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.is_mounted(device):
                log.warning(f"Device {device} is already mounted")
                return True

            if not os.path.exists(mount_point):
                os.makedirs(mount_point, exist_ok=True)

            run_command(
                f"mount {device} {mount_point}", shell=True, suppress_warning=True
            )
            log.info(f"Successfully mounted {device} to {mount_point}")
            return True

        except Exception as e:
            log.error(f"Error mounting {device} to {mount_point}: {e}", exc_info=True)
            return False

    def unmount_partition(self, mount_point: str) -> bool:
        """
        Safely unmount a partition.

        Args:
            mount_point: Directory to unmount

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            result = run_command(
                f"findmnt -n {mount_point}",
                shell=True,
                raise_on_fail=False,
                suppress_warning=True,
            )
            if result.return_code != 0:
                return True

            run_command(f"umount {mount_point}", shell=True, suppress_warning=True)
            log.info(f"Successfully unmounted {mount_point}")
            return True

        except Exception as e:
            log.error(f"Error unmounting {mount_point}: {e}", exc_info=True)
            return False

    def is_mounted(self, device: str) -> bool:
        """
        Check if a partition is mounted.

        Args:
            device: Device path to check

        Returns:
            bool: True if mounted, False otherwise
        """
        try:
            result = run_command(
                f"findmnt -n -S {device}",
                shell=True,
                raise_on_fail=False,
                suppress_warning=True,
            )
            return result.return_code == 0
        except Exception as e:
            log.error(f"Error checking if {device} is mounted: {e}", exc_info=True)
            return False

    def validate_partition_structure(self) -> bool:
        """
        Ensure required partitions exist and are accessible.

        Returns:
            bool: True if valid, False otherwise
        """
        required_partitions = [
            self.BOOT1_PATH,
            self.BOOT2_PATH,
            self.ROOT1_PATH,
            self.ROOT2_PATH,
            self.HOME_PATH,
        ]

        for partition in required_partitions:
            if not os.path.exists(partition):
                log.error(f"Required partition {partition} does not exist")
                return False

        return True

    def check_available_space(self, partition: str) -> int:
        """
        Check available space on a partition in bytes.

        Args:
            partition: Partition device path

        Returns:
            int: Available space in bytes
        """
        try:
            mount_point = None
            temp_mount = False

            if not self.is_mounted(partition):
                mount_point = f"/tmp/space_check_{os.path.basename(partition)}"
                if not os.path.exists(mount_point):
                    os.makedirs(mount_point, exist_ok=True)
                self.mount_partition(partition, mount_point)
                temp_mount = True
            else:
                result = run_command(
                    f"findmnt -n -o TARGET -S {partition}",
                    shell=True,
                    suppress_warning=True,
                )
                mount_point = result.stdout.strip()

            result = run_command(
                f"df -B1 --output=avail {mount_point} | tail -n1",
                shell=True,
                suppress_warning=True,
            )
            available_bytes = int(result.stdout.strip())

            if temp_mount:
                self.unmount_partition(mount_point)
                try:
                    os.rmdir(mount_point)
                except:
                    pass

            return available_bytes

        except Exception as e:
            log.error(
                f"Error checking available space on {partition}: {e}", exc_info=True
            )
            return 0
