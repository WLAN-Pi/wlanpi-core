from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"

    PROJECT_NAME: str = "wlanpi-core"

    PROJECT_DESCRIPTION: str = """
    The wlanpi-core API provides endpoints for applications on the WLAN Pi to share data. 🚀
    """

    TAGS_METADATA: list = [
        {
            "name": "system",
            "description": "Some system utility endpoints",
        },
    ]

    DEBUGGING: bool = False

    class Config:
        case_sensitive = True
        base_dir: Path = None


settings = Settings()

# when app is created, endpoints will be stored here for api landing page
endpoints = []
