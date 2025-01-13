from pathlib import Path

from pydantic_settings import BaseSettings

from wlanpi_core import constants


class Settings(BaseSettings):
    API_V1_STR: str = constants.API_V1_STR

    PROJECT_NAME: str = constants.PROJECT_NAME

    PROJECT_DESCRIPTION: str = constants.PROJECT_DESCRIPTION

    TAGS_METADATA: list = [
        {
            "name": "system",
            "description": "Some system utility endpoints",
        },
    ]

    class Config:
        case_sensitive = True
        base_dir: Path = None


settings = Settings()

# when app is created, endpoints will be stored here for api landing page
endpoints = []
