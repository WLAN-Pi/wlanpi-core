#!/usr/bin/env python3

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from wlanpi_core.cli.partitions.cli_utils import (
    check_root,
    echo_debug,
    echo_error,
    echo_status,
    validate_device,
)
from wlanpi_core.services.partitions.partition_service import PartitionService


def display_partition_info():
    """Display current partition information, based on boot-info bash script."""
    try:
        partition_service = PartitionService()
        boot_info = partition_service.get_boot_info()

        echo_status("A/B partition boot investigation")

        echo_debug("System information:")
        print(f"    {boot_info.get('system_info', 'Not available')}")

        echo_debug("Model information:")
        print(f"    {boot_info.get('model', 'Not available')}")
        print()

        echo_debug("OS issue information:")
        if os.path.exists("/etc/rpi-issue"):
            with open("/etc/rpi-issue", "r") as f:
                print(f"    {f.read().strip()}")
        else:
            print("    [File /etc/rpi-issue does not exist]")

        echo_debug("Current partition set analysis:")
        current_set = boot_info.get("current_set", "unknown")
        print(f"    Currently using partition set {current_set}")
        print(f"    Boot from: {boot_info.get('current_boot_dev', 'unknown')}")
        print(f"    Root from: {boot_info.get('current_root_dev', 'unknown')}")

        echo_debug("Current /etc/fstab contents:")
        if os.path.exists("/etc/fstab"):
            with open("/etc/fstab", "r") as f:
                for line in f:
                    print(f"    {line.rstrip()}")
        else:
            print("    [File /etc/fstab does not exist]")

        echo_debug("Mount points:")
        if "partition_layout" in boot_info:
            mount_info = boot_info["partition_layout"].split("\n")
            for line in mount_info:
                if "mmcblk0" in line:
                    print(f"    {line}")

        echo_debug("Current boot partition contents:")
        boot_contents = os.listdir("/boot")
        for item in boot_contents:
            print(f"    {item}")

        echo_debug("Contents of /boot/cmdline.txt:")
        print(f"    {boot_info.get('cmdline_txt', '[File does not exist]')}")

        echo_debug("Contents of /boot/cmdline-b.txt:")
        print(f"    {boot_info.get('cmdline_b_txt', '[File does not exist]')}")

        echo_debug("Contents of /boot/tryboot.txt:")
        print(f"    {boot_info.get('tryboot_txt', '[File does not exist]')}")

        echo_debug("Contents of /boot/autoboot.txt:")
        print(f"    {boot_info.get('autoboot_txt', '[File does not exist]')}")

        echo_debug(
            "Checking boot partition 1 autoboot.txt (controls boot device after power loss):"
        )
        if "boot1_autoboot_txt" in boot_info:
            print(f"    Contents of partition 1 autoboot.txt:")
            print(f"        {boot_info['boot1_autoboot_txt']}")
        else:
            print("    [Could not determine boot1 autoboot.txt contents]")

        echo_debug("Partition layout:")
        for line in boot_info.get("partition_layout", "Not available").split("\n"):
            print(f"    {line}")

        echo_debug("Partition usage statistics:")
        for line in boot_info.get("partition_usage", "Not available").split("\n"):
            print(f"    {line}")

        echo_debug("Kernel command line used:")
        print(f"    {boot_info.get('kernel_cmdline', 'Not available')}")

        echo_debug("Boot history:")
        for line in boot_info.get("boot_history", "Not available").split("\n"):
            print(f"    {line}")

        echo_debug("Boot messages related to mmc/partitions:")
        try:
            import subprocess

            dmesg_output = (
                subprocess.check_output(
                    "dmesg | grep -i -e mmc -e partition -e boot | head -20",
                    shell=True,
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )
            for line in dmesg_output.split("\n"):
                print(f"    {line}")
        except Exception:
            print("    [Could not get boot messages]")

        echo_debug("Summary:")
        print(
            f" - Currently on partition set: {boot_info.get('current_set', 'unknown')}"
        )
        print(
            f" - Current boot partition: {boot_info.get('current_boot_dev', 'unknown')}"
        )
        print(
            f" - Current root partition: {boot_info.get('current_root_dev', 'unknown')}"
        )
        print(
            f" - Default boot set in current autoboot.txt: {boot_info.get('DEFAULT_BOOT', 'unknown')}"
        )
        print(
            f" - Partition set that will boot after power loss: {boot_info.get('power_loss_boot', 'unknown')}"
        )
        print(
            f" - Boot partition 1 autoboot.txt setting: {boot_info.get('boot1_partition', 'None')}"
        )

        echo_status("Done")

    except Exception as e:
        echo_error(f"Failed to retrieve boot information: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description="Display partition diagnostic information"
    )
    parser.parse_args()
    check_root()
    validate_device()
    display_partition_info()


if __name__ == "__main__":
    main()
