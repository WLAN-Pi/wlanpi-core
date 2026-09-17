"""Application settings loaded from the environment."""

from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from wlanpi_core import constants
from wlanpi_core.api.openapi_docs import OPENAPI_DESCRIPTION, OPENAPI_TAGS


class Settings(BaseSettings):
    """Application configuration settings."""

    API_DEFAULT_TIMEOUT: int = 20

    ACCESS_TOKEN_EXPIRE_DAYS: int = 7

    API_V1_STR: str = constants.API_V1_STR

    PROJECT_NAME: str = constants.PROJECT_NAME

    PROJECT_DESCRIPTION: str = OPENAPI_DESCRIPTION

    TAGS_METADATA: list[Any] = OPENAPI_TAGS

    base_dir: Path = Path(__file__).parent.parent.absolute()

    model_config = SettingsConfigDict(case_sensitive=True)


settings = Settings()

# when app is created, endpoints will be stored here for api landing page
endpoints: list[Any] = []
