# -*- coding: utf-8 -*-
#
# wlanpi-core : backend services for the WLAN Pi
# Copyright : (c) 2021 Josh Schmelzle
# License : BSD-3-Clause
# Maintainer : josh@joshschmelzle.com


"""
wlanpi-core
~~~~~~~~~~~

backend services for the WLAN Pi
"""

# stdlib imports
import argparse
import os
import platform
import sys

# third party imports
import uvicorn

# app imports
from .__version__ import __version__


def setup_parser() -> argparse.ArgumentParser:
    """Set default values and handle arg parser"""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="wlanpi-core provides backend services for the WLAN pi. Read the manual with: man wlanpi-core",
    )
    parser.add_argument(
        "--reload", dest="development", action="store_true", default=False
    )
    parser.add_argument(
        "--version", "-V", "-v", action="version", version=f"{__version__}"
    )
    return parser


def confirm_prompt(question: str) -> bool:
    reply = None
    while reply not in ("y", "n"):
        reply = input(f"{question} (y/n): ").lower()
    return reply == "y"


def main():
    lets_go = confirm_prompt(
        "Running wlanpi-core directly which is normally run as a service... Are you sure?"
    )

    if lets_go:
        parser = setup_parser()
        args = parser.parse_args()
        uvicorn.run(
            "wlanpi_core.app:app",
            port=8000,
            host="0.0.0.0",
            reload=args.development,
        )


def init():
    """Handle main init"""
    # hard set no support for non linux platforms
    if "linux" not in sys.platform:
        sys.exit(
            "{0} only works on Linux... exiting...".format(os.path.basename(__file__))
        )

    # hard set no support for python < v3.7
    if sys.version_info < (3, 7):
        sys.exit(
            "{0} requires Python version 3.7 or higher...\nyou are trying to run with Python version {1}...\nexiting...".format(
                os.path.basename(__file__), platform.python_version()
            )
        )

    if __name__ == "__main__":
        sys.exit(main())


init()
