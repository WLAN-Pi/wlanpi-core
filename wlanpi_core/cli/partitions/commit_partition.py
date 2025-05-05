#!/usr/bin/env python3

import argparse
import os
import sys
import time

from wlanpi_core.cli.partitions.cli_utils import (
    check_root,
    echo_debug,
    echo_error,
    echo_status,
    validate_device,
)
from wlanpi_core.services.partitions.config_service import ConfigService
from wlanpi_core.services.partitions.image_handler import (
    ImageHandler,
    ImageHandlerError,
)
from wlanpi_core.services.partitions.lock_service import LockService
from wlanpi_core.services.partitions.partition_service import PartitionService
from wlanpi_core.services.partitions.update_manager import UpdateError, UpdateManager


def show_progress(message: str, progress: int = None):
    """Display a progress message with optional percent indicator."""
    progress_str = ""
    if progress is not None:
        progress_str = f"[{progress:3d}%] "
    print(f"\r{progress_str}{message}", end="")
    sys.stdout.flush()


def monitor_update_progress(update_manager: UpdateManager, interval: float = 0.5):
    """Monitor update progress and display updates."""
    last_step = None
    last_progress = None

    try:
        while True:
            status = update_manager.get_update_status()
            current_step = status.get("current_step")
            progress = status.get("progress", 0)

            if current_step != last_step or progress != last_progress:
                last_step = current_step
                last_progress = progress

                if current_step == update_manager.STEP_CHECK_PREREQUISITES:
                    show_progress("Checking prerequisites...", progress)
                elif current_step == update_manager.STEP_VERIFY_IMAGE:
                    show_progress("Verifying image integrity...", progress)
                elif current_step == update_manager.STEP_PREPARE_PARTITIONS:
                    show_progress("Preparing partitions...", progress)
                elif current_step == update_manager.STEP_EXTRACT_BOOT:
                    show_progress("Extracting boot partition...", progress)
                elif current_step == update_manager.STEP_EXTRACT_ROOT:
                    show_progress("Extracting root partition...", progress)
                elif current_step == update_manager.STEP_VERIFY_EXTRACTED:
                    show_progress("Verifying extracted partitions...", progress)
                elif current_step == update_manager.STEP_UPDATE_CONFIG:
                    show_progress("Updating configuration files...", progress)
                elif current_step == update_manager.STEP_FINALIZE:
                    show_progress("Finalizing update...", progress)
                else:
                    show_progress(f"Working... ({current_step})", progress)

            if status.get("status") in [
                update_manager.STATUS_COMPLETED,
                update_manager.STATUS_FAILED,
            ]:
                print()
                break

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nProgress monitoring interrupted. Update may still be running.")


def confirm_update(image_path: str, target_set: str, space_info: dict) -> bool:
    """Confirm with user before proceeding with update."""
    print("\nUpdate Summary:")
    print(f"  Image: {image_path}")
    print(f"  Target partition set: {target_set}")
    print(f"  Space required for boot: {space_info['boot_human']}")
    print(f"  Space required for root: {space_info['root_human']}")
    print(f"  Space available on boot: {space_info['available_space']['boot_human']}")
    print(f"  Space available on root: {space_info['available_space']['root_human']}")
    print("\nWARNING: This operation will overwrite the target partition set.")
    print("         Existing data on the target partitions will be lost.")

    while True:
        response = input("\nDo you want to continue? [y/N]: ").lower()
        if not response or response == "n":
            return False
        elif response == "y":
            return True
        else:
            print("Please answer 'y' or 'n'")


def update_alternate_partition(
    image_path: str, no_confirm: bool = False, no_verify: bool = False
) -> int:
    """
    Update the inactive partition set with a new OS image.

    Args:
        image_path: Path to the OS image
        no_confirm: Skip confirmation prompt if True
        no_verify: Skip image checksum verification if True

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    try:
        echo_status("Initializing services")
        lock_service = LockService()

        if lock_service.is_locked() and not lock_service.is_lock_stale():
            lock_info = lock_service.get_lock_status()
            echo_error(
                f"Another update operation is in progress.\n"
                f"Started by: {lock_info.get('requester', 'unknown')}\n"
                f"At: {lock_info.get('acquired_at', 'unknown')}\n"
                f"Use 'sudo release-update-lock' if you believe this is an error."
            )
            return 1

        if not lock_service.acquire_lock("update", "cli"):
            echo_error("Failed to acquire lock for update operation.")
            return 1

        try:
            partition_service = PartitionService()
            config_service = ConfigService()
            image_handler = ImageHandler()

            update_manager = UpdateManager(
                lock_service, partition_service, config_service, image_handler
            )

            echo_status("Preparing for update")
            prepare_result = update_manager.prepare_update(image_path)

            if not prepare_result["success"]:
                echo_error(
                    f"Failed to prepare for update: {prepare_result.get('message', 'Unknown error')}"
                )
                return 1

            details = prepare_result["details"]
            if not no_confirm and not confirm_update(
                image_path,
                details["target_set"],
                {
                    "boot_human": details["space_requirements"]["boot_human"],
                    "root_human": details["space_requirements"]["root_human"],
                    "available_space": details["available_space"],
                },
            ):
                echo_status("Update cancelled by user.")
                return 0

            echo_status("Starting update process")
            print("This may take several minutes. Please do not interrupt the process.")

            update_manager.execute_update(image_path)
            monitor_update_progress(update_manager)

            status = update_manager.get_update_status()
            if status["status"] == update_manager.STATUS_FAILED:
                echo_error(f"Update failed: {status.get('error', 'Unknown error')}")
                return 1

            echo_status("Update completed successfully")
            target_set = status["target_set"]
            echo_debug(f"Updated partition set {target_set}")

            print("\nNext steps:")
            print(
                f"1. Try booting into the new partition with: sudo tryboot-alternate-partition"
            )
            print(
                f"2. If the new system works well, make it the default with: sudo commit-current-partition"
            )
            print(
                f"3. If there are problems, you can revert back with: sudo rollback-partition"
            )

            return 0

        finally:
            lock_service.release_lock()

    except UpdateError as e:
        echo_error(f"Update error: {str(e)}")
        return 1
    except ImageHandlerError as e:
        echo_error(f"Image handling error: {str(e)}")
        return 1
    except Exception as e:
        echo_error(f"Unexpected error: {str(e)}")
        return 1


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Update the alternate partition set with a new OS image."
    )
    parser.add_argument("image_path", help="Path to the OS image file")
    parser.add_argument(
        "--no-confirm", action="store_true", help="Skip confirmation prompt"
    )
    parser.add_argument(
        "--no-verify", action="store_true", help="Skip image checksum verification"
    )
    args = parser.parse_args()

    check_root()

    validate_device()

    if not os.path.exists(args.image_path):
        echo_error(f"Image file not found: {args.image_path}")
        return 1

    return update_alternate_partition(
        args.image_path, no_confirm=args.no_confirm, no_verify=args.no_verify
    )


if __name__ == "__main__":
    sys.exit(main())
