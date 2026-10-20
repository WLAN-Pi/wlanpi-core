#!/usr/bin/python3

"""ASGI entry point; gunicorn serves `app` from here."""

import os

from wlanpi_core.app import create_app

debug = os.getenv("WLANPI_CORE_DEBUG", "False").lower() == "true"

app = create_app(debug=debug)
