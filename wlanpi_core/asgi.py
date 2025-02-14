#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
wlanpi_core.asgi
~~~~~~~~~~~~~~~~~
a web application for the WLAN Pi

run this from gunicorn
"""

import os

from wlanpi_core.app import create_app

debug = os.getenv("WLANPI_CORE_DEBUG", "False").lower() == "true"

app = create_app(debug=debug)
