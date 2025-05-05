#!/usr/bin/env python3

import argparse
import subprocess
import sys

from wlanpi_core.cli.partitions.cli_utils import (
    check_root,
    echo_debug,
    echo_error,
    echo_status,
    validate_device,
)
from wlanpi_core.services.partitions.config_service import ConfigService
from wlanpi_core.services.partitions.image_handler import ImageHandler
from wlanpi_core.services.partitions.lock_service import LockService
from wlanpi_core.services.partitions.partition_service import PartitionService
from wlanpi_core.services.partitions.update_manager import UpdateManager


def confirm_rollback() -> bool:
    """Confirm with user before rolling back to the alternate partition."""
    print(
        "\nWARNING: This will configure the system to boot into the alternate partition set."
    )
    print(
        "         The system will reboot after this operation if '--no-reboot' is not specified."
    )
    print("         Use this if the current partition is not working correctly.")

    while True:
        response = input("\nDo you want to continue? [y/N]: ").lower()
        if not response or response == "n":
            return False
        elif response == "y":
            return True
        else:
            print("Please answer 'y' or 'n'")


def rollback_partition(no_confirm: bool = False, no_reboot: bool = False) -> int:
    """
    Roll back to the alternate partition set.

    Args:
        no_confirm: Skip confirmation prompt if True
        no_reboot: Skip automatic reboot if True

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    try:
        echo_status("Initializing services")
        lock_service = LockService()

        if lock_service.is_locked() and not lock_service.is_lock_stale():
            lock_info = lock_service.get_lock_status()
            echo_error(
                f"Another partition operation is in progress.\n"
                f"Started by: {lock_info.get('requester', 'unknown')}\n"
                f"At: {lock_info.get('acquired_at', 'unknown')}\n"
                f"Use 'sudo release-update-lock' if you believe this is an error."
            )
            return 1

        if not lock_service.acquire_lock("rollback", "cli"):
            echo_error("Failed to acquire lock for rollback operation.")
            return 1

        try:
            partition_service = PartitionService()
            config_service = ConfigService()
            image_handler = ImageHandler()

            update_manager = UpdateManager(
                lock_service, partition_service, config_service, image_handler
            )

            current_set = partition_service.get_current_partition_set()
            alternate_set = partition_service.get_inactive_partition_set()

            if not no_confirm:
                echo_status(f"Current partition set: {current_set}")
                echo_status(f"Will roll back to: {alternate_set}")

                if not confirm_rollback():
                    echo_status("Operation cancelled.")
                    return 0

            echo_status(f"Rolling back to partition set {alternate_set}")
            result = update_manager.rollback_update()

            if not result["success"]:
                echo_error(f"Rollback failed: {result.get('message', 'Unknown error')}")
                return 1

            echo_status(
                f"Successfully configured system to boot into partition set {alternate_set} on next boot"
            )

            if not no_reboot:
                echo_status("Rebooting system in 5 seconds...")
                for i in range(5, 0, -1):
                    print(f"\r{i}...", end="")
                    sys.stdout.flush()
                    import time

                    time.sleep(1)
                print("\rRebooting now...")

                subprocess.run(["reboot"])
            else:
                echo_debug("To boot into the alternate partition, reboot the system.")

            return 0

        finally:
            lock_service.release_lock()

    except Exception as e:
        echo_error(f"Error: {str(e)}")
        return 1


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Roll back to the alternate partition set."
    )
    parser.add_argument(
        "--no-confirm", action="store_true", help="Skip confirmation prompt"
    )
    parser.add_argument(
        "--no-reboot", action="store_true", help="Skip automatic reboot after setup"
    )
    args = parser.parse_args()

    check_root()

    validate_device()

    return rollback_partition(no_confirm=args.no_confirm, no_reboot=args.no_reboot)


if __name__ == "__main__":
    sys.exit(main())
