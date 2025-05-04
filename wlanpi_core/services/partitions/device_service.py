import os
from typing import Optional

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class DeviceService:
    """
    Handles device identification and validation functionality.
    """

    DEVICE_INFO_PATH = "/home/.device-info/model"
    GO_DEVICE_MODEL = "Go"

    def is_go_device(self) -> bool:
        """
        Check if the current device is a WLAN Pi Go model.

        Returns:
            bool: True if device is a WLAN Pi Go, False otherwise
        """
        try:
            if not os.path.exists(self.DEVICE_INFO_PATH):
                log.warning(f"Device info file not found at {self.DEVICE_INFO_PATH}")
                return False

            with open(self.DEVICE_INFO_PATH, "r") as f:
                model = f.read().strip()

            if model != self.GO_DEVICE_MODEL:
                log.warning(
                    f"Device model '{model}' is not compatible with partition management"
                )
                return False

            return True

        except Exception as e:
            log.error(f"Error validating device: {str(e)}", exc_info=True)
            return False

    def get_device_model(self) -> str:
        """
        Get the device model string.

        Returns:
            str: Device model string, or "Unknown" if not available
        """
        try:
            if os.path.exists(self.DEVICE_INFO_PATH):
                with open(self.DEVICE_INFO_PATH, "r") as f:
                    return f.read().strip()
            return "Unknown"
        except Exception as e:
            log.error(f"Error getting device model: {str(e)}", exc_info=True)
            return "Unknown"

    def get_compatibility_error(self) -> Optional[str]:
        """
        Return detailed compatibility error message if any.

        Returns:
            Optional[str]: Error message or None if device is compatible
        """
        try:
            if not os.path.exists(self.DEVICE_INFO_PATH):
                return f"Device info file not found at {self.DEVICE_INFO_PATH}"

            with open(self.DEVICE_INFO_PATH, "r") as f:
                model = f.read().strip()

            if model != self.GO_DEVICE_MODEL:
                return f"Device model '{model}' is not compatible with partition management"

            return None

        except Exception as e:
            return f"Error validating device: {str(e)}"
