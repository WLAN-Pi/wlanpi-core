import sys

from wlanpi_core.services.partitions.device_service import DeviceService

BLUE = "\033[1;34m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
CYAN = "\033[1;36m"
RESET = "\033[0m"


def echo_status(msg: str) -> None:
    print(f"{BLUE}>>> {msg}{RESET}")


def echo_debug(msg: str) -> None:
    print(f"{CYAN}DEBUG: {msg}{RESET}")


def echo_warning(msg: str) -> None:
    print(f"{YELLOW}WARNING: {msg}{RESET}")


def echo_error(msg: str) -> None:
    print(f"{RED}ERROR: {msg}{RESET}")
    sys.exit(1)


def validate_device():
    """Validate the current device is allowed for partition management."""
    device_service = DeviceService()
    if not device_service.is_allowed_device():
        echo_error("Partition management is only available on certain WLAN Pi devices")
