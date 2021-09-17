from pathlib import Path

from pydantic import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"

    PROJECT_NAME: str = "wlanpi-core"

    PROJECT_DESCRIPTION = """
    The wlanpi-core API provides endpoints for applications on and off the WLAN Pi to share data. 🚀
    """

    TAGS_METADATA = [
        {
            "name": "diagnostics",
            "description": "Provides diagnostics information for the WLAN Pi",
        },
        {
            "name": "interface",
            "description": "Provides information for WLAN interfaces",
        },
        {
            "name": "front panel menu system",
            "description": "These are for the physical FPMS found on the WLAN Pi device",
        },
        {
            "name": "network information",
            "description": "Gather network information with these endpoints",
        },
        {
            "name": "profiler",
            "description": "Gathers client capability profiles",
            "externalDocs": {
                "description": "External profiler docs",
                "url": "https://github.com/wlan-pi/profiler",
            },
        },
        {
            "name": "speedtest",
            "description": "Everybody likes speed, right?",
        },
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
