"""
wlanpi-core package

This package provides core services for applications on and off the WLAN Pi.
"""

# init the wlanpi_core package
import pathlib

# used to build path for templates
from wlanpi_core.core.config import settings

settings.Config.base_dir = pathlib.Path(__file__).parent.absolute()
