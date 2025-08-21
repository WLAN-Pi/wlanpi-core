#!/opt/wlanpi-core/bin/python3

import hashlib
import hmac
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

SECRET_PATH = "/home/wlanpi/.local/share/wlanpi-core/secrets/shared_secret.bin"
"""
id:                 id/name of the config
namespace:          the name of the namespace to run it in
use_namespace:      if the namespace should be used or not (defaults to False)
mode:               either "managed" or "monitor"
iface_display_name: name of the interface for the scanning api to use (e.g. wlanpi<x> or myiface<x>)
phy:                the phy to use (defaults to phy0)
interface:          the interface to use (defaults to wlan0)
security ↓
    ssid:           SSID of the network
    security:       security standard to use, e.g. "WPA2-PSK"
    psk:            password of the network (optional)
    identity:       optional
    password:       optional
    client_cert:    optional
    private_key:    optional
    ca_cert:        optional
mlo:                whether to use mlo or not (optional, default False)
default_route:      whether to set this namespace as the default route (default False)
autostart_app:      name of the app defined in the apps list above (optional)
"""


class NetworkConfigCLI:
    def __init__(self):
        self.DEFAULT_CTRL_INTERFACE = "/run/wpa_supplicant"
        self.DEFAULT_CONFIG_DIR = "/etc/wpa_supplicant"
        self.DEFAULT_DHCP_DIR = "/etc/network/interfaces.d"
        self.PID_DIR = "/run/wifictl/pids"
        self.APPS_FILE = "/etc/wifictl/apps.json"
        self.WPA_LOG_FILE = "/tmp/wpa.log"
        self.secret_file = Path(SECRET_PATH)

        self.API_PORT = 8000
        self.HOST = "localhost"
        self.BASE = f"http://{self.HOST}:{self.API_PORT}/api/v1/network/config/"
        self.token = None
        self.existing_configs = {}

    def generate_signature(
        self, method: str, request_endpoint: str, request_body: str
    ) -> str:
        """
        Generates HMAC signature for the request using SHA256.
        Matches server-side calculation:
        canonical_string = f"{method}\n{path}\n{query_string}\n{body}"
        """

        parsed = urlparse(request_endpoint)
        path = parsed.path
        query_string = parsed.query

        if not query_string and "?" in request_endpoint:
            query_string = request_endpoint.split("?", 1)[1]

        if method.upper() == "GET":
            request_body = ""

        canonical_string = f"{method}\n{path}\n{query_string}\n{request_body}"
        secret = self.secret_file.read_bytes()
        signature = hmac.new(
            secret, canonical_string.encode(), hashlib.sha256
        ).hexdigest()

        return signature

    def get(self, url: str):
        try:
            signature = self.generate_signature("GET", url, json.dumps({}))
            headers = (
                {
                    "Authorization": f"Bearer {self.token}",
                    "accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Signature": signature,
                }
                if self.token
                else {}
            )
            response = requests.get(url, headers=headers)
            if not response.ok:
                print(f"Error: {response.status_code} - {response.text}")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"GET request failed: {e}")

    def post(self, url: str, data: dict):
        try:
            signature = self.generate_signature("POST", url, json.dumps(data))
            headers = (
                {
                    "Authorization": f"Bearer {self.token}",
                    "accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Signature": signature,
                }
                if self.token
                else {}
            )
            response = requests.post(url, json=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"POST request failed: {e}")

    def delete(self, url: str, data: dict):
        try:
            signature = self.generate_signature("DELETE", url, json.dumps(data))
            headers = (
                {
                    "Authorization": f"Bearer {self.token}",
                    "accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Signature": signature,
                }
                if self.token
                else {}
            )
            response = requests.delete(url, json=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"DELETE request failed: {e}")

    def get_token(self):
        try:
            getjwt_output = subprocess.run(
                [
                    "/usr/bin/getjwt",
                    "network_config_cli",
                    "--port",
                    str(self.API_PORT),
                    "--no-color",
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            try:
                token_json = json.loads(getjwt_output)
            except json.JSONDecodeError as e:
                print("Failed to parse token output as JSON:")
                print(getjwt_output)
                print(f"Error: {e}")
                sys.exit(1)
            token = token_json.get("access_token")
            if not token:
                print("Failed to retrieve token.")
                print(getjwt_output)
                sys.exit(1)
            print("Token retrieved successfully.")
            self.token = token
        except subprocess.CalledProcessError as e:
            print("Failed to run getjwt command:")
            print(e.stderr)
            print(f"Error: {e}")
            sys.exit(1)

    def view_configs(self):
        print("\nLoading existing configurations...\n")
        self.existing_configs = self.get(self.BASE)
        for i, cfg in enumerate(self.existing_configs.items()):
            key, value = cfg
            print(f"{i+1}. {key} - active: {value}")

    def status(self):
        print("\nLoading network configuration status...\n")
        status = self.get(self.BASE + "status")
        for ns, details in status.items():
            print(f"Namespace: {ns}")
            if not details:
                print("  No interfaces found.")
                continue
            for key, value in details.items():
                print(f"    Interface: {key}")
                for subkey, subvalue in value.items():
                    print(f"        {subkey}: {subvalue}")

    def new_config(self):
        config_id = input("Enter config ID: ").strip()
        namespace = input("Enter namespace (default 'wlanpi'): ").strip() or "wlanpi"
        use_namespace = (
            input("Use namespace? (y/n, default 'n'): ").strip().lower() == "y"
        )
        mode = (
            input("Enter mode (managed/monitor, default 'managed'): ").strip()
            or "managed"
        )
        iface_display_name = (
            input("Enter interface display name (default 'wlanpi0'): ").strip()
            or "wlanpi0"
        )
        phy = input("Enter phy (default 'phy0'): ").strip() or "phy0"
        interface = input("Enter interface (default 'wlan0'): ").strip() or "wlan0"
        ssid = input("Enter SSID: ").strip()
        security = input(
            "Enter security type (only supports WPA2-PSK currently): "
        ).strip()
        if security.lower() == "wpa2-psk":
            psk = input("Enter PSK: ").strip()
        else:
            print("not supported yet")
            return
        mlo = input("Use MLO? (y/n, default 'n'): ").strip().lower() == "y"
        default_route = (
            input("Set as default route? (y/n, default 'n'): ").strip().lower() == "y"
        )
        app_id = input(
            "Enter app to autostart (optional, configured in next step): "
        ).strip()
        if app_id:
            apps_file = Path(self.APPS_FILE)
            if not apps_file.exists():
                apps_file.touch()
            try:
                with apps_file.open("r") as f:
                    apps = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Failed to parse apps file {self.APPS_FILE}: {e}")
                return
            if app_id not in apps:
                print(f"App ID {app_id} not found in apps file.")
                create_new_app = input("Create new app? (y/n): ").strip().lower()
                if create_new_app == "y":
                    app_command = input("Enter start command for the new app: ").strip()
                    apps[app_id] = app_command
                    with apps_file.open("w") as f:
                        json.dump(apps, f, indent=4)

        config = {
            "id": config_id,
            "namespace": namespace,
            "use_namespace": use_namespace,
            "mode": mode,
            "iface_display_name": iface_display_name,
            "phy": phy,
            "interface": interface,
            "security": {"ssid": ssid, "security": security, "psk": psk},
            "mlo": mlo,
            "default_route": default_route,
            "autostart_app": app_id,
        }
        response = self.post(self.BASE, data=config)
        print(f"Configuration {config_id} created successfully.")

    def activate_config(self):
        self.view_configs()
        config_idx = input("Enter number of config to activate: ").strip()
        try:
            config_idx = int(config_idx) - 1
            if config_idx < 0 or config_idx >= len(self.existing_configs):
                print("Invalid configuration number.")
                return
            config = list(self.existing_configs.items())[config_idx]
            config_id = config[0]
            config_active = config[1]
        except ValueError:
            print("Invalid input. Please enter a number.")
            return
        override = False
        if config_active:
            print(f"Configuration {config_id} is already active.")
            override = (
                input("Override and activate anyway? (y/n): ").strip().lower() == "y"
            )
            if not override:
                print("Activation cancelled.")
                return
        print(f"Activating configuration {config_id}... (~30s)")
        response = self.post(
            self.BASE
            + f"activate/{config_id}?override_active={'true' if override else 'false'}",
            {},
        )
        print(f"Configuration {config_id} activated successfully.")

    def deactivate_config(self):
        self.view_configs()
        config_idx = input("Enter number of config to deactivate: ").strip()
        try:
            config_idx = int(config_idx) - 1
            if config_idx < 0 or config_idx >= len(self.existing_configs):
                print("Invalid configuration number.")
                return
            config = list(self.existing_configs.items())[config_idx]
            config_id = config[0]
            config_active = config[1]
        except ValueError:
            print("Invalid input. Please enter a number.")
            return
        override = False
        if not config_active:
            print(f"Configuration {config_id} is not active.")
            override = (
                input("Override and deactivate anyway? (y/n): ").strip().lower() == "y"
            )
            if not override:
                print("Deactivation cancelled.")
                return
        print(f"Deactivating configuration {config_id}...")
        response = self.post(
            self.BASE
            + f"deactivate/{config_id}?override_active={'true' if override else 'false'}",
            {},
        )
        print(f"Configuration {config_id} deactivated successfully.")

    def delete_config(self):
        self.view_configs()
        config_idx = input("Enter number of config to delete: ").strip()
        try:
            config_idx = int(config_idx) - 1
            if config_idx < 0 or config_idx >= len(self.existing_configs):
                print("Invalid configuration number.")
                return
            config = list(self.existing_configs.items())[config_idx]
            config_id = config[0]
            config_active = config[1]
        except ValueError:
            print("Invalid input. Please enter a number.")
            return
        override = False
        if config_active:
            print(f"Configuration {config_id} is active.")
            override = (
                input("Override and delete anyway? (y/n): ").strip().lower() == "y"
            )
            if not override:
                print("Deletion cancelled.")
                return
        print(f"Deleting configuration {config_id}...")
        response = self.delete(
            self.BASE + f"{config_id}?force={'true' if override else 'false'}", {}
        )
        print(f"Configuration {config_id} deactivated successfully.")

    def menu(self):
        print("\nNetwork Configuration CLI")
        print("1. View existing configurations")
        print("2. View network config status")
        print("3. Create new configuration")
        print("4. Activate configuration")
        print("5. Deactivate configuration")
        print("6. Delete configuration")
        print("7. Exit")

        choice = input("Select an option: ").strip()
        if choice == "1":
            self.view_configs()
        elif choice == "2":
            self.status()
        elif choice == "3":
            self.new_config()
        elif choice == "4":
            self.activate_config()
        elif choice == "5":
            self.deactivate_config()
        elif choice == "6":
            self.delete_config()
        elif choice == "7":
            print("Exiting...")
            sys.exit(0)
        else:
            print("Invalid choice. Please try again.")
        return self.menu()

    def main(self):
        print("WLAN Pi Core Network Config CLI")

        print("Authenticating...")
        self.get_token()

        return self.menu()


if __name__ == "__main__":
    networkconfigcli = NetworkConfigCLI()
    networkconfigcli.main()
