#!/usr/bin/python3

"""ASGI entry point for the WLAN Pi web application.

Run this from gunicorn.
"""

import os

from wlanpi_core.app import create_app

debug = os.getenv("WLANPI_CORE_DEBUG", "False").lower() == "true"

app = create_app(debug=debug)
