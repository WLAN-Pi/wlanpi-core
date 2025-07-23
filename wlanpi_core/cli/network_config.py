#!/opt/wlanpi-core/bin/python3

import argparse
import logging
import sys

from wlanpi_core.utils import network_config

logging.basicConfig(level=logging.INFO)

def main():
    parser = argparse.ArgumentParser(description="Network Service")
    parser.add_argument("id", help="ID of the config to use")

    args = parser.parse_args()

    try:
        status = network_config.activate_config(args.id)
        print(f"Connected: {status}")
    except Exception as e:
        logging.exception("Failed to connect")
        sys.exit(1)

if __name__ == "__main__":
    exit(main())