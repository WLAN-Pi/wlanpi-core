from pathlib import Path
from pydantic import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"

    PROJECT_NAME: str = "wlanpi-core"

    class Config:
        case_sensitive = True
        base_dir: Path = None


settings = Settings()
