from pathlib import Path
from pydantic import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"

    PROJECT_NAME: str = "wlanpi-core"
    
    PROJECT_DESCRIPTION = """
    The wlanpi-core API provides endpoints for applications on and off the WLAN Pi to share data. 🚀
    """

    class Config:
        case_sensitive = True
        base_dir: Path = None


settings = Settings()

# when app is created, endpoints will be stored here for api landing page
endpoints = []
