from pathlib import Path

from pydantic_settings import BaseSettings

from wlanpi_core import constants
from wlanpi_core.api.openapi_docs import OPENAPI_DESCRIPTION, OPENAPI_TAGS


class Settings(BaseSettings):
    API_DEFAULT_TIMEOUT: int = 20

    ACCESS_TOKEN_EXPIRE_DAYS: int = 7

    # Token survival across reboots on an RTC-less device.
    #   "boot_bound":       tokens die with the boot they were issued in.
    #                       Strongest: no reliance on wall clock, ever.
    #   "wall_clock_grace": tokens from a previous boot stay valid until
    #                       wall-clock expiry. Trusts the wall clock across
    #                       reboots, which only SSH/sudo users can set — the
    #                       same privilege that can mint tokens anyway. While
    #                       the clock lags the token's issuance time (early
    #                       boot, before NTP/fake-hwclock catch-up), such
    #                       tokens are rejected retryably, not purged.
    # Within a boot, both modes measure token age on CLOCK_BOOTTIME, so
    # setting the clock can never extend or resurrect a token issued this boot.
    TOKEN_LIFETIME_MODE: str = "boot_bound"

    API_V1_STR: str = constants.API_V1_STR

    PROJECT_NAME: str = constants.PROJECT_NAME

    PROJECT_DESCRIPTION: str = OPENAPI_DESCRIPTION

    TAGS_METADATA: list = OPENAPI_TAGS

    class Config:
        case_sensitive = True
        base_dir: Path = None


settings = Settings()

# when app is created, endpoints will be stored here for api landing page
endpoints = []
