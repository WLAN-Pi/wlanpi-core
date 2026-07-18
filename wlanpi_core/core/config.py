from pathlib import Path

from pydantic_settings import BaseSettings

from wlanpi_core import constants
from wlanpi_core.api.openapi_docs import OPENAPI_DESCRIPTION, OPENAPI_TAGS


class Settings(BaseSettings):
    API_DEFAULT_TIMEOUT: int = 20

    ACCESS_TOKEN_EXPIRE_DAYS: int = 7

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
