import os
from typing import Optional

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class DeviceService:
    """
    Handles device identification and validation functionality.
    """

    DEVICE_INFO_PATH = "/home/.device-info/model"

    DEVICE_ALLOWLIST = ["go"]

    def is_allowed_device(self) -> bool:
        """
        Check if the current device is an allowed WLAN Pi model for partition management.

        Returns:
            bool: True if device is an allowed WLAN Pi model, False otherwise
        """
        try:
            if not os.path.exists(self.DEVICE_INFO_PATH):
                log.warning(f"Device info file not found at {self.DEVICE_INFO_PATH}")
                return False

            with open(self.DEVICE_INFO_PATH, "r") as f:
                model = f.read().strip()

            if model.lower() not in self.DEVICE_ALLOWLIST:
                log.warning(
                    f"Device model '{model}' is not compatible with partition management"
                )
                return False

            return True

        except Exception:
            log.error(
                f"Error validating if device is allowed for partition management",
                exc_info=True,
            )
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
        except Exception:
            log.error(f"Error getting device model", exc_info=True)
            return "Unknown"

    def get_compatibility_error(self) -> Optional[str]:
        """
        Return detailed compatibility error message if any.

        Returns:
            Optional[str]: Error message or None if device is compatible
        """

        def sanitize(model: str) -> str:
            return model.lower().replace("wlan pi", "").replace("wlanpi", "").strip()

        try:
            model = None

            try:
                result = subprocess.run(
                    ["wlanpi-model"], capture_output=True, text=True, check=True
                )
                for line in result.stdout.splitlines():
                    if line.startswith("Model"):
                        model = line.split(":")[1]
                        model = sanitize(model)
                        break
            except FileNotFoundError:
                log.warning("Error: wlanpi-model command not found.")
            except subprocess.CalledProcessError as e:
                log.warning(f"Error running wlanpi-model: {e}")

            if model and self.is_allowed_device(model):
                return None

            model_from_device_info = None
            if os.path.exists(self.DEVICE_INFO_PATH):
                with open(self.DEVICE_INFO_PATH, "r") as f:
                    model_from_device_info = f.read()
                    model_from_device_info = sanitize(model_from_device_info)
                if model_from_device_info and self.is_allowed_device(
                    model_from_device_info
                ):
                    return None

            final_model = model if model else model_from_device_info

            if final_model:
                return f"Device model '{final_model}' is not compatible with partition management"
            else:
                return "Could not determine device model for compatibility check."

        except Exception as e:
            return f"Error validating device compatibility: {str(e)}"
