#!/opt/wlanpi-core/bin/python3

import argparse
import hashlib
import hmac
import json
import re
import socket
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    raise SystemExit(
        "The 'requests' package is required. Please install it with 'pip install requests'"
    )

DEFAULT_PORT = 31415
AUTH_ENDPOINT = "/api/v1/auth/token"
SECRET_PATH = "/home/wlanpi/.local/share/wlanpi-core/secrets/shared_secret.bin"
RED = "\033[0;31m"
BLUE = "\033[0;34m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
NC = "\033[0m"


class DeviceAuthClient:
    """Client for authenticating devices and obtaining JWT tokens via local API."""

    def __init__(self, device_id: str, port: int = DEFAULT_PORT) -> None:
        self.device_id = device_id
        self.port = port
        self.api_url = f"localhost:{port}"
        self.auth_endpoint = AUTH_ENDPOINT
        self.secret_file = Path(SECRET_PATH)
        self.validate_setup()

    def validate_setup(self) -> None:
        """
        Validate something is running on the port and file access.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect(("localhost", self.port))
        except OSError:
            raise RuntimeError(
                f"Nothing appears to be running on port {self.port}. "
                "Please ensure wlanpi-core server is running."
            )

        if not self.secret_file.exists():
            raise FileNotFoundError(f"Secret not found at {self.secret_file}")

        try:
            self.secret_file.read_bytes()
        except PermissionError:
            raise PermissionError("Secret exists but is not readable")

    def generate_signature(self, request_body: str) -> str:
        """
        Generates HMAC signature for the request using SHA256.
        """
        canonical_string = f"POST\n{self.auth_endpoint}\n\n{request_body}"
        secret = self.secret_file.read_bytes()
        signature = hmac.new(
            secret, canonical_string.encode(), hashlib.sha256
        ).hexdigest()

        return signature

    def get_token(self) -> dict[str, Any]:
        """
        Makes the API request to get the JWT token.
        """
        request_body = json.dumps({"device_id": self.device_id})
        signature = self.generate_signature(request_body)

        response = requests.post(
            f"http://{self.api_url}{self.auth_endpoint}",
            headers={
                "X-Request-Signature": signature,
                "accept": "application/json",
                "Content-Type": "application/json",
            },
            data=request_body,
            timeout=5,
        )
        response.raise_for_status()

        return response.json()


def colorize_json(json_str: str) -> str:
    """Colorize JSON string."""
    json_str = re.sub(r'"([^"]*)":', f'{BLUE}"\\1"{NC}:', json_str)
    json_str = re.sub(r':\s*"([^"]*)"', f': {GREEN}"\\1"{NC}', json_str)
    json_str = re.sub(r":\s*(-?\d+\.?\d*)", f": {YELLOW}\\1{NC}", json_str)
    json_str = re.sub(r":\s*(true|false|null)", f": {YELLOW}\\1{NC}", json_str)

    return json_str


def main() -> int:
    """Entry point for the JWT token generator."""
    parser = argparse.ArgumentParser(description="Generate JWT token for device")
    parser.add_argument("device_id", help="Device ID")
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"API port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colorized output",
    )

    args = parser.parse_args()

    try:
        client = DeviceAuthClient(args.device_id, args.port)
        token_response = client.get_token()
        json_str = json.dumps(token_response, indent=2)
        if args.no_color:
            print(json_str)
        else:
            print(colorize_json(json_str))
    except (FileNotFoundError, PermissionError) as e:
        print(f"{prefix if args.no_color else f'{RED}{prefix}'} {str(e)}{'' if args.no_color else NC}")
        return 1
    except requests.RequestException as e:
        print(f"{prefix if args.no_color else f'{RED}{prefix}'} {str(e)}{'' if args.no_color else NC}")
        return 1
    except Exception as e:
        print(f"{prefix if args.no_color else f'{RED}{prefix}'} {str(e)}{'' if args.no_color else NC}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
