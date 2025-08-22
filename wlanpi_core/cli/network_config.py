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
        self.APPS_FILE = "/home/wlanpi/.local/share/wlanpi-core/netcfg/apps.json"
        self.WPA_LOG_FILE = "/tmp/wpa.log"
        self.secret_file = Path(SECRET_PATH)

        self.API_PORT = 31415
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
            
    def patch(self, url: str, data: dict):
        try:
            signature = self.generate_signature("PATCH", url, json.dumps(data))
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
            response = requests.patch(url, json=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"PATCH request failed: {e}")

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

    def view_configs(self, no_default=True):
        print("\nLoading existing configurations...\n")
        self.existing_configs = self.get(self.BASE)
        # Filter out "default" and "root" keys at the beginning
        configs = {
            k: v
            for k, v in self.existing_configs.items()
            if not (no_default and k in ["default", "root"])
        }
        self.existing_configs = configs
        if not configs:
            print("No configurations found.")
            return
        max_len = max(len(key) for key in configs.keys())
        for idx, (key, value) in enumerate(configs.items(), 1):
            print(f"{idx}. {key.ljust(max_len+2)} active: {value}")

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

    def prompt_app_id(self):
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
                return None
            if app_id not in apps:
                print(f"App ID {app_id} not found in apps file.")
                create_new_app = input("Create new app? (y/n): ").strip().lower()
                if create_new_app == "y":
                    app_command = input("Enter start command for the new app: ").strip()
                    apps[app_id] = app_command
                    with apps_file.open("w") as f:
                        json.dump(apps, f, indent=4)
                else:
                    return None
        return app_id

    def prompt_network_config(self, is_namespace=True, existing_data=None):
        """
        Prompt user for network config values, showing defaults and using existing values where available.
        """
        def prompt_field(prompt_text, existing_value=None, default_value=None, required=False, transform=None):
            """
            Helper to prompt for a field, showing existing and default values.
            """
            if existing_value is not None:
                prompt = f"{prompt_text} [current: '{existing_value}'] (press Enter to keep): "
            elif default_value is not None:
                prompt = f"{prompt_text} [default: '{default_value}']: "
            else:
                prompt = f"{prompt_text}: "
            val = input(prompt).strip()
            if val == "" and existing_value is not None:
                print(f"Using existing value: '{existing_value}'")
                return existing_value
            elif val == "" and default_value is not None:
                print(f"Using default value: '{default_value}'")
                return default_value
            elif val == "" and required:
                print("This field is required.")
                return prompt_field(prompt_text, existing_value, default_value, required, transform)
            return transform(val) if transform else val

        config = {}

        # Namespace
        if is_namespace:
            ns = prompt_field(
                "Enter namespace",
                existing_value=existing_data.get("namespace") if existing_data else None,
                default_value="wlanpi"
            )
            config["namespace"] = ns

        # Mode
        mode = prompt_field(
            "Enter mode (managed/monitor)",
            existing_value=existing_data.get("mode") if existing_data else None,
            default_value="managed"
        )
        config["mode"] = mode

        # iface_display_name
        iface_display = prompt_field(
            "Enter interface display name",
            existing_value=existing_data.get("iface_display_name") if existing_data else None,
            default_value="wlanpi0"
        )
        config["iface_display_name"] = iface_display

        # phy
        phy = prompt_field(
            "Enter phy",
            existing_value=existing_data.get("phy") if existing_data else None,
            default_value="phy0"
        )
        config["phy"] = phy

        # interface
        interface = prompt_field(
            "Enter interface",
            existing_value=existing_data.get("interface") if existing_data else None,
            default_value="wlan0"
        )
        config["interface"] = interface

        # Security
        existing_security = existing_data.get("security", {}) if existing_data else {}
        use_security = prompt_field(
            "Do you want to configure security? (y/n)",
            existing_value="y" if existing_data and existing_data.get("security") else None,
            default_value="y",
            transform=lambda v: v == "y"
        )
        
        if use_security:
                
            ssid = prompt_field(
                "Enter SSID",
                existing_value=existing_security.get("ssid"),
                default_value=""
            )

            print("Only WPA2-PSK is supported for now.")
            psk = prompt_field(
                "Enter PSK",
                existing_value=existing_security.get("psk"),
                default_value=""
            )

            config["security"] = {
                "ssid": ssid,
                "security": "WPA2-PSK",
                "psk": psk
            }

        # mlo
        mlo = prompt_field(
            "Use MLO? (y/n)",
            existing_value="y" if existing_data and existing_data.get("mlo") else None,
            default_value="n",
            transform=lambda v: v.lower()
        )
        config["mlo"] = (mlo == "y")

        # default_route
        default_route = prompt_field(
            "Set as default route? (y/n)",
            existing_value="y" if existing_data and existing_data.get("default_route") else None,
            default_value="n",
            transform=lambda v: v.lower()
        )
        config["default_route"] = (default_route == "y")

        # autostart_app
        existing_app = existing_data.get("autostart_app") if existing_data else None
        if existing_app:
            print(f"Existing autostart_app: {existing_app}")
        app_id = self.prompt_app_id()
        if app_id:
            config["autostart_app"] = app_id
        elif existing_app:
            config["autostart_app"] = existing_app

        print("\nConfiguration preview:")
        print(json.dumps(config, indent=4))
        confirm = input("Save this config module? (y/n): ").strip().lower()
        if confirm != "y":
            print("Config module discarded.")
            return None

        return config

    def new_config(self):
        config_id = input("Enter config ID: ").strip()
        namespaces = []
        if input("Add a namespace config? (y/n or enter): ").strip().lower() == "y":
            while True:
                print("\nAdding a new namespace configuration:\n")
                ns_cfg = self.prompt_network_config(is_namespace=True)
                if ns_cfg:
                    namespaces.append(ns_cfg)
                another = input("Add another namespace? (y/n or enter): ").strip().lower()
                if another != "y":
                    break

        roots = []
        if input("Add a root config? (y/n or enter): ").strip().lower() == "y":
            while True:
                print("\nAdding a new root configuration:\n")
                root_cfg = self.prompt_network_config(is_namespace=False)
                if root_cfg:
                    roots.append(root_cfg)
                another = input("Add another root config? (y/n or enter): ").strip().lower()
                if another != "y":
                    break

        config = {
            "id": config_id,
            "namespaces": namespaces if namespaces else None,
            "roots": roots if roots else None,
        }

        response = self.post(self.BASE, data=config)
        print(f"Configuration {config_id} created successfully.")
        
    def edit_config(self):
        self.view_configs()
        config_idx = input("Enter number of config to edit: ").strip()
        try:
            config_idx = int(config_idx) - 1
            if config_idx < 0 or config_idx >= len(self.existing_configs):
                print("Invalid configuration number.")
                return
            config = list(self.existing_configs.items())[config_idx]
            config_id = config[0]
        except ValueError:
            print("Invalid input. Please enter a number.")
            return

        print(f"Editing configuration {config_id}.")
        
        existing_config = self.get(self.BASE + config_id)

        namespaces = []
        ns_idx = 0
        len_namespaces = len(existing_config.get("namespaces", []))
        if input("Edit namespace configs? (y/n or enter): ").strip().lower() == "y":
            while True:
                print("\nEditing/adding a namespace configuration:\n")
                ns_cfg = self.prompt_network_config(is_namespace=True, existing_data=existing_config.get("namespaces", [])[ns_idx] if ns_idx < len_namespaces else None)
                if ns_cfg:
                    namespaces.append(ns_cfg)
                another = input("Edit/add another namespace? (y/n or enter): ").strip().lower()
                if another != "y":
                    break
                ns_idx += 1

        roots = []
        root_idx = 0
        len_roots = len(existing_config.get("roots", []))
        if input("Edit root configs? (y/n or enter): ").strip().lower() == "y":
            while True:
                print("\nEditing/adding a root configuration:\n")
                root_cfg = self.prompt_network_config(is_namespace=False, existing_data=existing_config.get("roots", [])[root_idx] if root_idx < len_roots else None)
                if root_cfg:
                    roots.append(root_cfg)
                another = input("Edit/add another root config? (y/n or enter): ").strip().lower()
                if another != "y":
                    break

        config = {
            "id": config_id,
            "namespaces": namespaces if namespaces else None,
            "roots": roots if roots else None,
        }

        response = self.patch(self.BASE + f"{config_id}", data=config)
        print(f"Configuration {config_id} edited successfully.")

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
        while True:
            print("\nNetwork Configuration CLI")
            options = [
                ("View existing configurations", self.view_configs),
                ("View network config status", self.status),
                ("Create new configuration", self.new_config),
                ("Edit existing configuration", self.edit_config),
                ("Delete configuration", self.delete_config),
                ("Activate configuration", self.activate_config),
                ("Deactivate configuration", self.deactivate_config),
                ("Exit", sys.exit),
            ]
            for i, (option, _) in enumerate(options, 1):
                print(f"{i}. {option}")

            choice = input("Select an option: ").strip()
            try:
                idx = int(choice) - 1
                if idx < 0 or idx >= len(options):
                    raise ValueError
                func = options[idx][1]
                func()
            except (ValueError, IndexError):
                print("Invalid choice. Please try again.")

    def main(self):
        print("WLAN Pi Core Network Config CLI")

        print("Authenticating...")
        self.get_token()

        return self.menu()


if __name__ == "__main__":
    networkconfigcli = NetworkConfigCLI()
    try:
        networkconfigcli.main()
    except KeyboardInterrupt:
        print("\nExiting Network Configuration CLI.")
