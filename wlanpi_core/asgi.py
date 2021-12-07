#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
wlanpi_core.asgi
~~~~~~~~~~~~~~~~~
a web application for the WLAN Pi

run this from gunicorn
"""

from wlanpi_core.app import create_app

app = create_app()
