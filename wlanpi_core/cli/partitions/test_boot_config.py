#1/usr/bin/env python3

import argparse
import sys

from wlanpi_core.cli.partitions.cli_utils import (
    check_root,
    echo_debug, 
    echo_error, 
    echo_status,
    validate_device
)
from wlanpi_core.services.partitions.config_service import ConfigService
from wlanpi_core.services.partitions.partition_service import PartitionService


def show_boot_config():
    """Show current boot configuration."""
    try:
        config_service = ConfigService()
        partition_service = PartitionService()
        
        current_set = partition_service.get_current_partition_set()
        inactive_set = partition_service.get_inactive_partition_set()
        boot_info = partition_service.get_boot_info()
        boot_history = config_service.get_boot_history()
        
        echo_status("Current Boot Configuration")
        
        echo_debug("Partition information:")
        print(f"  - Current partition set: {current_set}")
        print(f"  - Inactive partition set: {inactive_set}")
        print(f"  - Current boot partition: {boot_info.get('current_boot_dev', 'Unknown')}")
        print(f"  - Current root partition: {boot_info.get('current_root_dev', 'Unknown')}")
        print(f"  - Boot after power loss: {boot_info.get('power_loss_boot', 'Unknown')}")
        
        echo_debug("Boot configuration files:")
        print(f"  - cmdline.txt:\n{boot_info.get('cmdline_txt', 'Not found')}")
        print()
        print(f"  - autoboot.txt:\n{boot_info.get('autoboot_txt', 'Not found')}")
        print()
        print(f"  - tryboot.txt:\n{boot_info.get('tryboot_txt', 'Not found')}")
        print()
        
        echo_debug("Boot history:")
        for entry in boot_history.get("boot_entries", []):
            print(f"  - {entry.get('id', '')}: {entry.get('time', '')}")
        
        echo_status("Use other commands to modify boot configuration")
        
    except Exception as e:
        echo_error(f"Failed to show boot configuration: {str(e)}")


def main():
    parser = argparse.ArgumentParser(description="Boot configuration utility")
    parser.add_argument("--show", action="store_true", help="Show current boot configuration")
    args = parser.parse_args()
    
    check_root()
    validate_device()
    print("fuck")
    if args.show or len(sys.argv) == 1:
        show_boot_config()


if __name__ == "__main__":
    main()
