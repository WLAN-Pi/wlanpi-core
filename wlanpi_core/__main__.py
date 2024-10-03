# -*- coding: utf-8 -*-
#
# wlanpi-core : backend services for the WLAN Pi
# Copyright : (c) 2023 Josh Schmelzle
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


def port(port) -> int:
    """Check if the provided port is valid"""
    try:
        # make sure port is an int
        port = int(port)
    except ValueError:
        raise ValueError("%s is not a number")

    port_ranges = [(1024, 65353)]

    for _range in port_ranges:
        if _range[0] <= port <= _range[1]:
            return port

    raise ValueError("%s not a valid. Pick a port between %s.", port, port_ranges)


def setup_parser() -> argparse.ArgumentParser:
    """Set default values and handle arg parser"""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="wlanpi-core provides backend services for the WLAN Pi. Read the manual with: man wlanpi-core",
    )
    parser.add_argument(
        "--reload", dest="livereload", action="store_true", default=False
    )
    parser.add_argument("--port", "-p", dest="port", type=port, default=8000)
    parser.add_argument(
        "--debug",
        "-d",
        dest="debug",
        action="store_true",
        default=False,
        help="Enable debugging",
    )
    parser.add_argument(
        "--version", "-V", "-v", action="version", version=f"{__version__}"
    )
    return parser


def main() -> None:
    parser = setup_parser()
    args = parser.parse_args()

    print(
        "WARNING!!! Starting wlanpi-core directly with uvicorn. This is typically ONLY for quick testing and debugging!"
    )

    if not args.livereload:
        print(
            "Consider running with --reload for live reload as you iterate on hotfixes or features..."
        )

    if os.getenv("WLANPI_CORE_DEBUGGING") == "1":
        print("WLANPI_CORE_DEBUGGING is set to 1... debugging already enabled...")
    else:
        if args.debug:
            os.environ["WLANPI_CORE_DEBUGGING"] = "1"
        else:
            print("Consider running with --debug or -d to increase the debug level...")

    print("\n")

    uvicorn.run(
        "wlanpi_core.asgi:app", port=args.port, host="0.0.0.0", reload=args.livereload
    )


def init() -> None:
    """Handle main init"""
    # hard set no support for non linux platforms
    if "linux" not in sys.platform:
        sys.exit(
            "{0} only works on Linux... exiting...".format(os.path.basename(__file__))
        )

    # hard set no support for python < v3.9
    if sys.version_info < (3, 9):
        sys.exit(
            "{0} requires Python version 3.9 or higher...\nyou are trying to run with Python version {1}...\nexiting...".format(
                os.path.basename(__file__), platform.python_version()
            )
        )

    if __name__ == "__main__":
        sys.exit(main())


init()
