#
# wlanpi-core : backend services for the WLAN Pi
# Copyright : (c) 2025 Josh Schmelzle
# License : BSD-3-Clause
# Maintainer : josh@joshschmelzle.com


"""Backend services for the WLAN Pi."""

# stdlib imports
import argparse
import os
import sys
from typing import Any

# third party imports
import uvicorn

# app imports
from .__version__ import __version__


def port(port: Any) -> int:
    """Check if the provided port is valid."""
    try:
        # make sure port is an int
        port = int(port)
    except ValueError:
        raise ValueError("%s is not a number") from None

    port_ranges = [(1024, 65353)]

    for _range in port_ranges:
        if _range[0] <= port <= _range[1]:
            return port

    raise ValueError("%s not a valid. Pick a port between %s.", port, port_ranges)


def setup_parser() -> argparse.ArgumentParser:
    """Set default values and handle arg parser."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="wlanpi-core provides backend services for the WLAN Pi. Read the manual with: man wlanpi-core",
    )
    parser.add_argument(
        "--reload",
        dest="livereload",
        action="store_true",
        default=False,
        help="Enable live reload for development",
    )
    parser.add_argument(
        "--port",
        "-p",
        dest="port",
        type=port,
        default=8000,
        help="Port number to run the server on",
    )
    parser.add_argument(
        "--debug",
        "-d",
        dest="debug",
        action="store_true",
        default=False,
        help="Enable debug mode with verbose logging",
    )
    parser.add_argument(
        "--version", "-V", "-v", action="version", version=f"{__version__}"
    )
    return parser


def main() -> None:
    """Run the uvicorn server using the parsed CLI arguments."""
    parser = setup_parser()
    args = parser.parse_args()

    if not args.livereload:
        print(
            "Consider running with --reload for live reload as you iterate on hotfixes or features...\n"
        )

    import os

    os.environ["WLANPI_CORE_DEBUG"] = str(args.debug)

    uvicorn.run(
        "wlanpi_core.asgi:app",
        port=args.port,
        host="127.0.0.1",
        reload=args.livereload,
    )


def init() -> None:
    """Handle main init."""
    # hard set no support for non linux platforms
    if "linux" not in sys.platform:
        sys.exit(f"{os.path.basename(__file__)} only works on Linux... exiting...")

    if __name__ == "__main__":
        main()


init()
