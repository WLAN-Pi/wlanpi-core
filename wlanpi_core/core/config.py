"""Application settings loaded from the environment."""

import logging
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from wlanpi_core import constants
from wlanpi_core.api.openapi_docs import OPENAPI_DESCRIPTION, OPENAPI_TAGS

log = logging.getLogger(__name__)

VALID_WLAN_MANAGEMENT = ("auto", "manual")


class Settings(BaseSettings):
    """Application configuration settings."""

    API_DEFAULT_TIMEOUT: int = 20

    ACCESS_TOKEN_EXPIRE_DAYS: int = 7

    API_V1_STR: str = constants.API_V1_STR

    PROJECT_NAME: str = constants.PROJECT_NAME

    PROJECT_DESCRIPTION: str = OPENAPI_DESCRIPTION

    TAGS_METADATA: list[Any] = OPENAPI_TAGS

    base_dir: Path = Path(__file__).parent.parent.absolute()

    # "auto": wlanpi-core manages Wi-Fi interfaces (default).
    # "manual": wlanpi-core leaves Wi-Fi entirely to the operator.
    WLAN_MANAGEMENT: str = "auto"

    @field_validator("WLAN_MANAGEMENT", mode="before")
    @classmethod
    def _normalize_wlan_management(cls, value: Any) -> str:
        """Accept only auto/manual; fall back to auto so startup never fails."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in VALID_WLAN_MANAGEMENT:
                return normalized
        log.warning("Invalid WLAN_MANAGEMENT=%r; falling back to 'auto'", value)
        return "auto"

    model_config = SettingsConfigDict(case_sensitive=True)


settings = Settings()


def wlan_management_is_manual() -> bool:
    """Return True when wlanpi-core is configured to leave Wi-Fi alone."""
    return settings.WLAN_MANAGEMENT == "manual"


# when app is created, endpoints will be stored here for api landing page
endpoints: list[Any] = []
