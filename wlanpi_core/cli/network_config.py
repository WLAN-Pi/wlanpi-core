#!/opt/wlanpi-core/bin/python3

import hashlib
import hmac
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse
import argparse

import requests

SECRET_PATH = "/home/wlanpi/.local/share/wlanpi-core/secrets/shared_secret.bin"

# Enhanced security type definitions with detailed descriptions
SECURITY_TYPES = {
    "OPEN": {
        "name": "Open Network",
        "description": "No authentication required",
        "fields": []
    },
    "WPA2-PSK": {
        "name": "WPA2-PSK",
        "description": "WPA2 with pre-shared key (most common)",
        "fields": ["psk"]
    },
    "WPA3-PSK": {
        "name": "WPA3-PSK (SAE)",
        "description": "WPA3 with pre-shared key (newer, more secure)",
        "fields": ["psk"]
    },
    "WPA2-EAP": {
        "name": "WPA2-Enterprise",
        "description": "WPA2 with 802.1X authentication (corporate networks)",
        "fields": ["identity", "password", "eap_method", "ca_cert"]
    },
    "WPA3-EAP": {
        "name": "WPA3-Enterprise", 
        "description": "WPA3 with 802.1X authentication (corporate networks)",
        "fields": ["identity", "password", "eap_method", "ca_cert"]
    },
    "802.1X": {
        "name": "802.1X",
        "description": "Generic 802.1X authentication",
        "fields": ["identity", "password", "eap_method", "ca_cert"]
    },
    "OWE": {
        "name": "OWE (Enhanced Open)",
        "description": "Opportunistic Wireless Encryption",
        "fields": []
    },
    "WEP": {
        "name": "WEP (Legacy)",
        "description": "Deprecated - use only if absolutely necessary",
        "fields": ["wep_key"]
    },
    "OPENROAMING": {
        "name": "OpenRoaming/Passpoint",
        "description": "Hotspot 2.0 / Passpoint networks",
        "fields": ["identity", "client_cert", "private_key", "ca_cert"]
    }
}

EAP_METHODS = {
    "PEAP": {
        "name": "PEAP",
        "description": "Protected EAP (most common for username/password)",
        "phase2_methods": ["MSCHAPV2", "GTC", "MD5"],
        "requires_cert": False
    },
    "TLS": {
        "name": "EAP-TLS",
        "description": "Certificate-based authentication (most secure)",
        "phase2_methods": [],
        "requires_cert": True
    },
    "TTLS": {
        "name": "EAP-TTLS",
        "description": "Tunneled TLS",
        "phase2_methods": ["PAP", "CHAP", "MSCHAPV2"],
        "requires_cert": False
    },
    "PWD": {
        "name": "EAP-PWD",
        "description": "Password-based authentication",
        "phase2_methods": [],
        "requires_cert": False
    }
}

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

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

    def print_header(self, text: str, char: str = "="):
        """Print a formatted header"""
        print(f"\n{char * 60}")
        print(f" {text}")
        print(f"{char * 60}")

    def print_info(self, text: str):
        """Print informational message"""
        print(f"ℹ️  {text}")

    def print_warning(self, text: str):
        """Print warning message"""
        print(f"⚠️  {text}")

    def print_error(self, text: str):
        """Print error message"""
        print(f"❌ {text}")

    def print_success(self, text: str):
        """Print success message"""
        print(f"✅ {text}")

    def validate_network_name(self, name: str) -> bool:
        """Validate network configuration name"""
        if not name or len(name.strip()) == 0:
            raise ValidationError("Configuration name cannot be empty")
        if len(name) > 64:
            raise ValidationError("Configuration name too long (max 64 characters)")
        if not name.replace('_', '').replace('-', '').isalnum():
            raise ValidationError("Configuration name can only contain letters, numbers, hyphens, and underscores")
        return True

    def validate_ssid(self, ssid: str) -> bool:
        """Validate SSID"""
        if not ssid or len(ssid.strip()) == 0:
            raise ValidationError("SSID cannot be empty")
        if len(ssid.encode('utf-8')) > 32:
            raise ValidationError("SSID too long (max 32 bytes in UTF-8)")
        return True

    def validate_psk(self, psk: str) -> bool:
        """Validate PSK/password"""
        if not psk:
            raise ValidationError("PSK/password cannot be empty")
        if len(psk) == 64 and all(c in '0123456789abcdefABCDEF' for c in psk):
            # Hex PSK
            return True
        elif 8 <= len(psk) <= 63:
            # Passphrase
            return True
        else:
            raise ValidationError("PSK must be 8-63 characters or 64 hex characters")

    def validate_interface_name(self, name: str) -> bool:
        """Validate interface name"""
        if not name or len(name.strip()) == 0:
            raise ValidationError("Interface name cannot be empty")
        if len(name) > 15:  # Linux interface name limit
            raise ValidationError("Interface name too long (max 15 characters)")
        return True

    def validate_file_path(self, path: str) -> bool:
        """Validate file path exists"""
        if not path:
            return True  # Optional field
        if not Path(path).exists():
            raise ValidationError(f"File does not exist: {path}")
        return True

    def get_available_phys(self) -> List[str]:
        """Get list of available PHY interfaces"""
        try:
            result = subprocess.run(['iw', 'phy'], capture_output=True, text=True, check=True)
            phys = []
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Phy #'):
                    # Extract phy name from "Phy #0 (phy0)"
                    if '(phy' in line and ')' in line:
                        phy_name = line.split('(phy')[1].split(')')[0]
                        phys.append(f"phy{phy_name}")
            return phys if phys else ["phy0"]  # Fallback to phy0
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.print_warning("Could not detect available PHY interfaces, using default")
            return ["phy0"]

    def get_available_interfaces(self) -> List[str]:
        """Get list of available network interfaces"""
        try:
            result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True, check=True)
            interfaces = []
            for line in result.stdout.split('\n'):
                if ': ' in line and 'wl' in line:  # Look for wireless interfaces
                    interface = line.split(': ')[1].split('@')[0]
                    if 'wlan' in interface or 'wlp' in interface:
                        interfaces.append(interface)
            return interfaces if interfaces else ["wlan0"]  # Fallback to wlan0
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.print_warning("Could not detect available interfaces, using default")
            return ["wlan0"]

    def generate_signature(self, method: str, request_endpoint: str, request_body: str) -> str:
        """Generate HMAC signature for the request using SHA256"""
        parsed = urlparse(request_endpoint)
        path = parsed.path
        query_string = parsed.query

        if not query_string and "?" in request_endpoint:
            query_string = request_endpoint.split("?", 1)[1]

        if method.upper() == "GET":
            request_body = ""

        canonical_string = f"{method}\n{path}\n{query_string}\n{request_body}"
        secret = self.secret_file.read_bytes()
        signature = hmac.new(secret, canonical_string.encode(), hashlib.sha256).hexdigest()
        return signature

    def make_request(self, method: str, url: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make HTTP request with proper error handling"""
        try:
            json_data = json.dumps(data) if data else "{}"
            signature = self.generate_signature(method, url, json_data)
            headers = {
                "Authorization": f"Bearer {self.token}",
                "accept": "application/json",
                "Content-Type": "application/json",
                "X-Request-Signature": signature,
            } if self.token else {}

            print(f"Making {method} request...")
            
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=30)
            elif method == "POST":
                response = requests.post(url, json=data, headers=headers, timeout=60)
            elif method == "PATCH":
                response = requests.patch(url, json=data, headers=headers, timeout=60)
            elif method == "DELETE":
                response = requests.delete(url, json=data, headers=headers, timeout=60)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if not response.ok:
                self.print_error(f"Request failed: {response.status_code} - {response.text}")
                return None
                
            response.raise_for_status()
            return response.json()
            
        except requests.Timeout:
            self.print_error("Request timed out. The server may be busy.")
            return None
        except requests.ConnectionError:
            self.print_error("Could not connect to the server. Is the service running?")
            return None
        except requests.RequestException as e:
            self.print_error(f"Request failed: {e}")
            return None

    def get_token(self):
        """Get authentication token"""
        try:
            print("Authenticating with server...")
            getjwt_output = subprocess.run(
                ["/usr/bin/getjwt", "network_config_cli", "--port", str(self.API_PORT), "--no-color"],
                capture_output=True, text=True, check=True, timeout=10
            ).stdout
            
            try:
                token_json = json.loads(getjwt_output)
            except json.JSONDecodeError as e:
                self.print_error("Failed to parse token output as JSON:")
                print(getjwt_output)
                sys.exit(1)
                
            token = token_json.get("access_token")
            if not token:
                self.print_error("Failed to retrieve token from response")
                print(getjwt_output)
                sys.exit(1)
                
            self.token = token
            self.print_success("Authentication successful")
            
        except subprocess.TimeoutExpired:
            self.print_error("Token request timed out")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            self.print_error("Failed to run getjwt command:")
            print(e.stderr)
            sys.exit(1)
        except FileNotFoundError:
            self.print_error("getjwt command not found. Is wlanpi-core installed?")
            sys.exit(1)

    def view_configs(self, no_default=True):
        """View existing configurations with enhanced formatting"""
        self.print_header("Loading Network Configurations")
        
        configs_data = self.make_request("GET", self.BASE)
        if not configs_data:
            return
            
        self.existing_configs = {
            k: v for k, v in configs_data.items()
            if not (no_default and k in ["default", "root"])
        }
        
        if not self.existing_configs:
            self.print_info("No user configurations found.")
            return
            
        print("\nAvailable Configurations:")
        print("-" * 80)
        max_len = max(len(key) for key in self.existing_configs.keys())
        
        for idx, (key, is_active) in enumerate(self.existing_configs.items(), 1):
            status = "🟢 Active" if is_active else "⚪ Inactive"
            print(f"{idx:2d}. {key.ljust(max_len + 2)} {status}")
            
        print("-" * 80)
        print(f"Total configurations: {len(self.existing_configs)}")

    def status(self):
        """Show network status with enhanced formatting"""
        self.print_header("Network Configuration Status")
        
        status_data = self.make_request("GET", self.BASE + "status")
        if not status_data:
            return
            
        if not status_data:
            self.print_info("No active network configurations found.")
            return
            
        for ns, details in status_data.items():
            print(f"\n📡 Namespace: {ns}")
            if not details:
                print("   └── No active interfaces")
                continue
            
            total_items = len(details)
            for idx, (iface, info) in enumerate(details.items()):
                is_last_iface = idx == total_items - 1
                iface_prefix = "   └──" if is_last_iface else "   ├──"
                child_prefix = "       " if is_last_iface else "   │   "
                print(f"{iface_prefix} Interface: {iface}")
                info_items = list(info.items())
                for j, (key, value) in enumerate(info_items):
                    is_last_info = j == len(info_items) - 1
                    branch = f"{child_prefix}└──" if is_last_info else f"{child_prefix}├──"
                    if key == "wpa_status" and isinstance(value, dict):
                        state = value.get("wpa_state", "Unknown")
                        ssid = value.get("ssid", "Not connected")
                        print(f"{branch} Status: {state}")
                        if ssid != "Not connected":
                            print(f"{child_prefix}├── SSID: {ssid}")
                            if "bssid" in value:
                                print(f"{child_prefix}├── BSSID: {value['bssid']}")
                    elif key == "connected_scan" and isinstance(value, dict):
                        signal = value.get("signal")
                        if signal:
                            print(f"{branch} Signal: {signal} dBm")
                        freq = value.get("freq")
                        if freq:
                            print(f"{child_prefix}└── Frequency: {freq} MHz")
                    elif not isinstance(value, dict):
                        print(f"{branch} {key}: {value}")

    def prompt_security_type(self, existing_security: Optional[Dict] = None) -> str:
        """Enhanced security type selection"""
        self.print_header("Security Configuration", "-")
        
        current_type = existing_security.get("security") if existing_security else None
        if current_type:
            print(f"Current security type: {current_type}")
            
        print("\nAvailable Security Types:")
        print("-" * 60)
        
        security_list = list(SECURITY_TYPES.items())
        for idx, (sec_type, info) in enumerate(security_list, 1):
            current_marker = " (current)" if sec_type == current_type else ""
            print(f"{idx:2d}. {info['name']}{current_marker}")
            print(f"    {info['description']}")
            
        while True:
            try:
                if current_type:
                    choice = input(f"\nSelect security type [1-{len(security_list)}] (Enter to keep current): ").strip()
                    if not choice:
                        return current_type
                else:
                    choice = input(f"\nSelect security type [1-{len(security_list)}]: ").strip()
                    
                if not choice.isdigit():
                    raise ValueError("Please enter a number")
                    
                idx = int(choice) - 1
                if idx < 0 or idx >= len(security_list):
                    raise ValueError(f"Please enter a number between 1 and {len(security_list)}")
                    
                selected_type = security_list[idx][0]
                self.print_success(f"Selected: {SECURITY_TYPES[selected_type]['name']}")
                return selected_type
                
            except ValueError as e:
                self.print_error(str(e))

    def prompt_eap_method(self, existing_method: Optional[str] = None) -> Tuple[str, Optional[str]]:
        """Enhanced EAP method selection"""
        print("\nEAP Method Configuration:")
        print("-" * 40)
        
        if existing_method:
            print(f"Current EAP method: {existing_method}")
            
        eap_list = list(EAP_METHODS.items())
        for idx, (method, info) in enumerate(eap_list, 1):
            current_marker = " (current)" if method == existing_method else ""
            cert_req = " [Requires Certificate]" if info["requires_cert"] else ""
            print(f"{idx}. {info['name']}{current_marker}{cert_req}")
            print(f"   {info['description']}")
            
        while True:
            try:
                if existing_method:
                    choice = input(f"\nSelect EAP method [1-{len(eap_list)}] (Enter to keep current): ").strip()
                    if not choice:
                        selected_method = existing_method
                        break
                else:
                    choice = input(f"\nSelect EAP method [1-{len(eap_list)}]: ").strip()
                    
                if not choice.isdigit():
                    raise ValueError("Please enter a number")
                    
                idx = int(choice) - 1
                if idx < 0 or idx >= len(eap_list):
                    raise ValueError(f"Please enter a number between 1 and {len(eap_list)}")
                    
                selected_method = eap_list[idx][0]
                break
                
            except ValueError as e:
                self.print_error(str(e))

        # Handle Phase 2 authentication for methods that support it
        phase2_method = None
        method_info = EAP_METHODS[selected_method]
        
        if method_info["phase2_methods"]:
            print(f"\nPhase 2 Authentication for {method_info['name']}:")
            for idx, phase2 in enumerate(method_info["phase2_methods"], 1):
                print(f"{idx}. {phase2}")
                
            while True:
                try:
                    choice = input(f"Select Phase 2 method [1-{len(method_info['phase2_methods'])}] (default: 1): ").strip()
                    if not choice:
                        phase2_method = method_info["phase2_methods"][0]
                        break
                    if not choice.isdigit():
                        raise ValueError("Please enter a number")
                    idx = int(choice) - 1
                    if idx < 0 or idx >= len(method_info["phase2_methods"]):
                        raise ValueError(f"Please enter a number between 1 and {len(method_info['phase2_methods'])}")
                    phase2_method = method_info["phase2_methods"][idx]
                    break
                except ValueError as e:
                    self.print_error(str(e))

        return selected_method, phase2_method

    def prompt_field_with_validation(self, prompt: str, validator=None, existing_value=None, 
                                   default_value=None, required=False, secret=False, multiline=False) -> str:
        """Enhanced field prompting with validation"""
        attempts = 0
        max_attempts = 3
        
        while attempts < max_attempts:
            try:
                # Build prompt text
                prompt_text = prompt
                if existing_value is not None:
                    if secret:
                        prompt_text += f" [current: ***] (Enter to keep): "
                    else:
                        prompt_text += f" [current: '{existing_value}'] (Enter to keep): "
                elif default_value is not None:
                    prompt_text += f" [default: '{default_value}']: "
                else:
                    prompt_text += ": "
                
                if secret:
                    import getpass
                    value = getpass.getpass(prompt_text)
                elif multiline:
                    print(prompt_text + " (Enter empty line to finish)")
                    lines = []
                    while True:
                        line = input()
                        if not line:
                            break
                        lines.append(line)
                    value = '\n'.join(lines)
                else:
                    value = input(prompt_text).strip()
                
                # Handle empty responses
                if value == "":
                    if existing_value is not None:
                        if not secret:
                            self.print_info(f"Using existing value: '{existing_value}'")
                        return existing_value
                    elif default_value is not None:
                        self.print_info(f"Using default value: '{default_value}'")
                        return default_value
                    elif required:
                        raise ValidationError("This field is required and cannot be empty")
                    else:
                        return ""
                
                # Validate if validator provided
                if validator:
                    validator(value)
                    
                return value
                
            except ValidationError as e:
                attempts += 1
                self.print_error(f"Validation error: {e}")
                if attempts >= max_attempts:
                    self.print_error("Too many validation errors. Skipping this field.")
                    return existing_value or default_value or ""
            except KeyboardInterrupt:
                print("\nOperation cancelled by user")
                return existing_value or default_value or ""
                
        return existing_value or default_value or ""

    def prompt_security_config(self, security_type: str, existing_security: Optional[Dict] = None) -> Dict:
        """Enhanced security configuration prompting"""
        config = {"security": security_type}
        existing_security = existing_security or {}
        
        # Always prompt for SSID
        config["ssid"] = self.prompt_field_with_validation(
            "Enter SSID",
            validator=self.validate_ssid,
            existing_value=existing_security.get("ssid"),
            required=True
        )
        
        # Configure based on security type
        if security_type in ["WPA2-PSK", "WPA3-PSK"]:
            config["psk"] = self.prompt_field_with_validation(
                "Enter PSK/Password",
                validator=self.validate_psk,
                existing_value=existing_security.get("psk"),
                required=True,
                secret=True
            )
            
        elif security_type in ["WPA2-EAP", "WPA3-EAP", "802.1X"]:
            # EAP Method selection
            eap_method, phase2_method = self.prompt_eap_method(existing_security.get("eap_method"))
            config["eap_method"] = eap_method
            if phase2_method:
                config["phase2_method"] = phase2_method
            
            # Common EAP fields
            config["identity"] = self.prompt_field_with_validation(
                "Enter username/identity",
                existing_value=existing_security.get("identity"),
                required=True
            )
            
            # Check if certificate-based authentication
            if EAP_METHODS[eap_method]["requires_cert"]:
                self.print_info("Certificate-based authentication selected")
                config["client_cert"] = self.prompt_field_with_validation(
                    "Enter client certificate path",
                    validator=self.validate_file_path,
                    existing_value=existing_security.get("client_cert"),
                    required=True
                )
                config["private_key"] = self.prompt_field_with_validation(
                    "Enter private key path",
                    validator=self.validate_file_path,
                    existing_value=existing_security.get("private_key"),
                    required=True
                )
                
                # Private key password (optional)
                config["private_key_passwd"] = self.prompt_field_with_validation(
                    "Enter private key password (optional)",
                    existing_value=existing_security.get("private_key_passwd"),
                    secret=True
                )
            else:
                # Password-based authentication
                config["password"] = self.prompt_field_with_validation(
                    "Enter password",
                    existing_value=existing_security.get("password"),
                    required=True,
                    secret=True
                )
            
            # CA Certificate
            config["ca_cert"] = self.prompt_field_with_validation(
                "Enter CA certificate path (optional)",
                validator=self.validate_file_path,
                existing_value=existing_security.get("ca_cert"),
                default_value="/etc/ssl/certs/ca-certificates.crt"
            )
            
            # Optional advanced fields
            if input("Configure advanced options? (y/n): ").lower() == 'y':
                config["anonymous_identity"] = self.prompt_field_with_validation(
                    "Enter anonymous identity (optional)",
                    existing_value=existing_security.get("anonymous_identity")
                )
                config["subject_match"] = self.prompt_field_with_validation(
                    "Enter subject match (optional)",
                    existing_value=existing_security.get("subject_match")
                )
                config["domain_suffix_match"] = self.prompt_field_with_validation(
                    "Enter domain suffix match (optional)",
                    existing_value=existing_security.get("domain_suffix_match")
                )
                
        elif security_type == "OPENROAMING":
            self.print_info("OpenRoaming/Passpoint configuration")
            config["identity"] = self.prompt_field_with_validation(
                "Enter identity",
                existing_value=existing_security.get("identity"),
                required=True
            )
            config["client_cert"] = self.prompt_field_with_validation(
                "Enter client certificate path",
                validator=self.validate_file_path,
                existing_value=existing_security.get("client_cert"),
                required=True
            )
            config["private_key"] = self.prompt_field_with_validation(
                "Enter private key path",
                validator=self.validate_file_path,
                existing_value=existing_security.get("private_key"),
                required=True
            )
            config["ca_cert"] = self.prompt_field_with_validation(
                "Enter CA certificate path",
                validator=self.validate_file_path,
                existing_value=existing_security.get("ca_cert"),
                required=True
            )
            
        elif security_type == "WEP":
            self.print_warning("WEP is deprecated and insecure. Use only if absolutely necessary.")
            config["wep_key"] = self.prompt_field_with_validation(
                "Enter WEP key",
                existing_value=existing_security.get("wep_key"),
                required=True,
                secret=True
            )
            
        return config

    def prompt_app_id(self, existing_app: Optional[str] = None):
        """Enhanced app configuration"""
        self.print_header("Application Configuration", "-")
        
        if existing_app:
            print(f"Current autostart app: {existing_app}")
            
        apps_file = Path(self.APPS_FILE)
        existing_apps = {}
        
        if apps_file.exists():
            try:
                with apps_file.open("r") as f:
                    existing_apps = json.load(f)
            except json.JSONDecodeError:
                self.print_warning("Could not parse apps file")
        
        if existing_apps:
            print("\nAvailable applications:")
            for idx, (app_id, command) in enumerate(existing_apps.items(), 1):
                current_marker = " (current)" if app_id == existing_app else ""
                print(f"{idx}. {app_id}{current_marker}: {command}")
        
        app_id = self.prompt_field_with_validation(
            "Enter app ID to autostart (optional)",
            existing_value=existing_app
        )
        
        if app_id and app_id not in existing_apps:
            create_new = input(f"App '{app_id}' not found. Create new app? (y/n): ").lower() == 'y'
            if create_new:
                command = self.prompt_field_with_validation(
                    "Enter command for new app",
                    required=True
                )
                existing_apps[app_id] = command
                
                # Create directory if needed
                apps_file.parent.mkdir(parents=True, exist_ok=True)
                
                try:
                    with apps_file.open("w") as f:
                        json.dump(existing_apps, f, indent=4)
                    self.print_success(f"Created new app: {app_id}")
                except Exception as e:
                    self.print_error(f"Could not save app: {e}")
                    return None
            else:
                return None
                
        return app_id if app_id else None

    def prompt_network_config(self, is_namespace=True, existing_data=None):
        """Enhanced network configuration prompting"""
        config_type = "Namespace" if is_namespace else "Root"
        self.print_header(f"{config_type} Configuration")
        
        existing_data = existing_data or {}
        config = {}

        # Namespace (only for namespace configs)
        if is_namespace:
            config["namespace"] = self.prompt_field_with_validation(
                "Enter namespace name",
                existing_value=existing_data.get("namespace"),
                default_value="wlanpi",
                required=True
            )

        # Mode selection
        print("\nInterface Mode:")
        print("1. managed (normal WiFi client)")
        print("2. monitor (packet capture)")
        
        current_mode = existing_data.get("mode", "managed")
        while True:
            try:
                choice = input(f"Select mode [1-2] (current: {current_mode}): ").strip()
                if not choice:
                    config["mode"] = current_mode
                    break
                if choice == "1":
                    config["mode"] = "managed"
                    break
                elif choice == "2":
                    config["mode"] = "monitor"
                    break
                else:
                    raise ValueError("Please enter 1 or 2")
            except ValueError as e:
                self.print_error(str(e))

        # PHY selection with auto-detection
        available_phys = self.get_available_phys()
        print(f"\nAvailable PHY interfaces: {', '.join(available_phys)}")
        config["phy"] = self.prompt_field_with_validation(
            "Enter PHY interface",
            existing_value=existing_data.get("phy"),
            default_value=available_phys[0] if available_phys else "phy0"
        )

        # Interface selection with auto-detection
        available_interfaces = self.get_available_interfaces()
        if available_interfaces:
            print(f"\nDetected wireless interfaces: {', '.join(available_interfaces)}")
        config["interface"] = self.prompt_field_with_validation(
            "Enter base interface name",
            validator=self.validate_interface_name,
            existing_value=existing_data.get("interface"),
            default_value=available_interfaces[0] if available_interfaces else "wlan0"
        )

        # Display interface name
        config["iface_display_name"] = self.prompt_field_with_validation(
            "Enter display interface name",
            validator=self.validate_interface_name,
            existing_value=existing_data.get("iface_display_name"),
            default_value="wlanpi0"
        )

        # Security configuration (skip for monitor mode)
        if config["mode"] != "monitor":
            configure_security = input("Configure wireless security? (y/n): ").lower() == 'y'
            if configure_security or existing_data.get("security"):
                security_type = self.prompt_security_type(existing_data.get("security"))
                if security_type != "OPEN":
                    config["security"] = self.prompt_security_config(security_type, existing_data.get("security"))
                else:
                    config["security"] = {"security": "OPEN", "ssid": self.prompt_field_with_validation(
                        "Enter SSID", validator=self.validate_ssid, required=True
                    )}
        else:
            print("Monitor mode selected - skipping security configuration")

        # Advanced options
        print("\n" + "-" * 40)
        print("Advanced Configuration Options")
        print("-" * 40)

        # MLO (Wi-Fi 7 Multi-Link Operation)
        if input("Configure MLO (Multi-Link Operation) for Wi-Fi 7? (y/n): ").lower() == 'y':
            config["mlo"] = input("Enable MLO? (y/n): ").lower() == 'y'
        else:
            config["mlo"] = existing_data.get("mlo", False)

        # Default route
        config["default_route"] = input("Set as default route? (y/n): ").lower() == 'y'

        # Autostart application
        if input("Configure autostart application? (y/n): ").lower() == 'y':
            app_id = self.prompt_app_id(existing_data.get("autostart_app"))
            if app_id:
                config["autostart_app"] = app_id

        # Configuration preview and confirmation
        self.print_header("Configuration Preview", "-")
        self._preview_config(config)
        
        if input("\nSave this configuration? (y/n): ").lower() != 'y':
            self.print_warning("Configuration discarded")
            return None

        return config

    def _preview_config(self, config: Dict):
        """Display configuration preview in a readable format"""
        print(f"Configuration Type: {'Namespace' if 'namespace' in config else 'Root'}")
        
        for key, value in config.items():
            if key == "security" and isinstance(value, dict):
                print(f"Security Configuration:")
                for sec_key, sec_value in value.items():
                    if sec_key in ["psk", "password", "private_key_passwd", "wep_key"]:
                        print(f"  {sec_key}: ***")
                    else:
                        print(f"  {sec_key}: {sec_value}")
            else:
                print(f"{key}: {value}")

    def _validate_config_completeness(self, config: Dict) -> bool:
        """Validate that configuration is complete and consistent"""
        issues = []
        
        # Check required fields
        if config.get("mode") == "managed" and not config.get("security"):
            issues.append("Managed mode typically requires security configuration")
        
        if config.get("security"):
            sec = config["security"]
            if not sec.get("ssid"):
                issues.append("SSID is required when security is configured")
            
            sec_type = sec.get("security", "")
            if sec_type in ["WPA2-PSK", "WPA3-PSK"] and not sec.get("psk"):
                issues.append(f"{sec_type} requires PSK")
            elif sec_type in ["WPA2-EAP", "WPA3-EAP", "802.1X"]:
                if not sec.get("identity"):
                    issues.append(f"{sec_type} requires identity/username")
                if sec.get("eap_method") == "TLS" and not sec.get("client_cert"):
                    issues.append("EAP-TLS requires client certificate")

        if issues:
            print("\nConfiguration Issues:")
            for issue in issues:
                self.print_warning(issue)
            
            if input("Continue anyway? (y/n): ").lower() != 'y':
                return False
                
        return True

    def new_config(self):
        """Enhanced new configuration creation"""
        self.print_header("Create New Network Configuration")
        
        # Configuration ID with validation
        config_id = self.prompt_field_with_validation(
            "Enter configuration ID/name",
            validator=self.validate_network_name,
            required=True
        )
        
        # Check if ID already exists
        if config_id in self.existing_configs:
            self.print_error(f"Configuration '{config_id}' already exists")
            if input("Edit existing configuration instead? (y/n): ").lower() == 'y':
                return self.edit_config_by_id(config_id)
            return

        config = {"id": config_id}
        namespaces = []
        roots = []

        # Namespace configurations
        if input("Add namespace configuration(s)? (y/n): ").lower() == 'y':
            while True:
                print(f"\nAdding namespace configuration #{len(namespaces) + 1}")
                ns_cfg = self.prompt_network_config(is_namespace=True)
                if ns_cfg and self._validate_config_completeness(ns_cfg):
                    namespaces.append(ns_cfg)
                    self.print_success("Namespace configuration added")
                else:
                    self.print_warning("Namespace configuration was not added")
                
                if input("Add another namespace configuration? (y/n): ").lower() != 'y':
                    break

        # Root configurations  
        if input("Add root configuration(s)? (y/n): ").lower() == 'y':
            while True:
                print(f"\nAdding root configuration #{len(roots) + 1}")
                root_cfg = self.prompt_network_config(is_namespace=False)
                if root_cfg and self._validate_config_completeness(root_cfg):
                    roots.append(root_cfg)
                    self.print_success("Root configuration added")
                else:
                    self.print_warning("Root configuration was not added")
                
                if input("Add another root configuration? (y/n): ").lower() != 'y':
                    break

        # Validate we have at least one configuration
        if not namespaces and not roots:
            self.print_error("At least one namespace or root configuration is required")
            return

        config["namespaces"] = namespaces if namespaces else None
        config["roots"] = roots if roots else None

        # Final preview and confirmation
        self.print_header("Complete Configuration Preview")
        print(f"Configuration ID: {config_id}")
        print(f"Namespace configs: {len(namespaces)}")
        print(f"Root configs: {len(roots)}")
        
        if input("\nCreate this configuration? (y/n): ").lower() != 'y':
            self.print_warning("Configuration creation cancelled")
            return

        # Submit configuration
        print("Creating configuration...")
        response = self.make_request("POST", self.BASE, data=config)
        if response:
            self.print_success(f"Configuration '{config_id}' created successfully")
        else:
            self.print_error("Failed to create configuration")

    def edit_config_by_id(self, config_id: str):
        """Edit existing configuration by ID"""
        existing_config = self.make_request("GET", self.BASE + config_id)
        if not existing_config:
            return
            
        self.print_header(f"Editing Configuration: {config_id}")
        
        namespaces = []
        roots = []
        
        # Edit namespaces
        existing_namespaces = existing_config.get("namespaces", [])
        if existing_namespaces or input("Edit/add namespace configurations? (y/n): ").lower() == 'y':
            ns_idx = 0
            while True:
                existing_ns = existing_namespaces[ns_idx] if ns_idx < len(existing_namespaces) else None
                action = "Editing" if existing_ns else "Adding new"
                print(f"\n{action} namespace configuration #{ns_idx + 1}")
                
                ns_cfg = self.prompt_network_config(is_namespace=True, existing_data=existing_ns)
                if ns_cfg and self._validate_config_completeness(ns_cfg):
                    namespaces.append(ns_cfg)
                elif existing_ns:
                    # Keep existing if user cancelled edit
                    namespaces.append(existing_ns)
                
                ns_idx += 1
                if ns_idx >= len(existing_namespaces) and input("Add another namespace? (y/n): ").lower() != 'y':
                    break
                elif ns_idx < len(existing_namespaces) and input("Edit next namespace? (y/n): ").lower() != 'y':
                    # Add remaining unchanged namespaces
                    namespaces.extend(existing_namespaces[ns_idx:])
                    break

        # Edit roots
        existing_roots = existing_config.get("roots", [])
        if existing_roots or input("Edit/add root configurations? (y/n): ").lower() == 'y':
            root_idx = 0
            while True:
                existing_root = existing_roots[root_idx] if root_idx < len(existing_roots) else None
                action = "Editing" if existing_root else "Adding new"
                print(f"\n{action} root configuration #{root_idx + 1}")
                
                root_cfg = self.prompt_network_config(is_namespace=False, existing_data=existing_root)
                if root_cfg and self._validate_config_completeness(root_cfg):
                    roots.append(root_cfg)
                elif existing_root:
                    # Keep existing if user cancelled edit
                    roots.append(existing_root)
                
                root_idx += 1
                if root_idx >= len(existing_roots) and input("Add another root config? (y/n): ").lower() != 'y':
                    break
                elif root_idx < len(existing_roots) and input("Edit next root config? (y/n): ").lower() != 'y':
                    # Add remaining unchanged roots
                    roots.extend(existing_roots[root_idx:])
                    break

        config = {
            "id": config_id,
            "namespaces": namespaces if namespaces else None,
            "roots": roots if roots else None,
        }

        print("Updating configuration...")
        response = self.make_request("PATCH", self.BASE + config_id, data=config)
        if response:
            self.print_success(f"Configuration '{config_id}' updated successfully")
        else:
            self.print_error("Failed to update configuration")

    def edit_config(self):
        """Enhanced configuration editing"""
        self.view_configs()
        if not self.existing_configs:
            return
            
        config_idx = input("Enter number of config to edit: ").strip()
        try:
            config_idx = int(config_idx) - 1
            if config_idx < 0 or config_idx >= len(self.existing_configs):
                self.print_error("Invalid configuration number")
                return
            config_id = list(self.existing_configs.keys())[config_idx]
            self.edit_config_by_id(config_id)
        except ValueError:
            self.print_error("Please enter a valid number")

    def activate_config(self):
        """Enhanced configuration activation"""
        self.view_configs()
        if not self.existing_configs:
            return
            
        config_idx = input("Enter number of config to activate: ").strip()
        try:
            config_idx = int(config_idx) - 1
            if config_idx < 0 or config_idx >= len(self.existing_configs):
                self.print_error("Invalid configuration number")
                return
                
            config_items = list(self.existing_configs.items())
            config_id = config_items[config_idx][0]
            config_active = config_items[config_idx][1]
            
        except ValueError:
            self.print_error("Please enter a valid number")
            return

        override = False
        if config_active:
            self.print_warning(f"Configuration '{config_id}' is already active")
            override = input("Override and activate anyway? (y/n): ").lower() == 'y'
            if not override:
                self.print_info("Activation cancelled")
                return

        print(f"Activating configuration '{config_id}'...")
        print("This may take up to 30 seconds...")
        
        start_time = time.time()
        response = self.make_request(
            "POST",
            f"{self.BASE}activate/{config_id}?override_active={'true' if override else 'false'}",
            data={}
        )
        
        elapsed = time.time() - start_time
        if response:
            self.print_success(f"Configuration '{config_id}' activated successfully in {elapsed:.1f}s")
            
            # Show connection status after activation
            if input("Show connection status? (y/n): ").lower() == 'y':
                time.sleep(2)  # Allow time for connection to establish
                self.status()
        else:
            self.print_error("Failed to activate configuration")

    def deactivate_config(self):
        """Enhanced configuration deactivation"""
        self.view_configs()
        if not self.existing_configs:
            return
            
        config_idx = input("Enter number of config to deactivate: ").strip()
        try:
            config_idx = int(config_idx) - 1
            if config_idx < 0 or config_idx >= len(self.existing_configs):
                self.print_error("Invalid configuration number")
                return
                
            config_items = list(self.existing_configs.items())
            config_id = config_items[config_idx][0]
            config_active = config_items[config_idx][1]
            
        except ValueError:
            self.print_error("Please enter a valid number")
            return

        if not config_active:
            self.print_warning(f"Configuration '{config_id}' is not active")
            override = input("Continue anyway? (y/n): ").lower() == 'y'
            if not override:
                self.print_info("Deactivation cancelled")
                return

        print(f"Deactivating configuration '{config_id}'...")
        response = self.make_request(
            "POST",
            f"{self.BASE}deactivate/{config_id}",
            data={}
        )
        
        if response:
            self.print_success(f"Configuration '{config_id}' deactivated successfully")
        else:
            self.print_error("Failed to deactivate configuration")

    def delete_config(self):
        """Enhanced configuration deletion"""
        self.view_configs()
        if not self.existing_configs:
            return
            
        config_idx = input("Enter number of config to delete: ").strip()
        try:
            config_idx = int(config_idx) - 1
            if config_idx < 0 or config_idx >= len(self.existing_configs):
                self.print_error("Invalid configuration number")
                return
                
            config_items = list(self.existing_configs.items())
            config_id = config_items[config_idx][0]
            config_active = config_items[config_idx][1]
            
        except ValueError:
            self.print_error("Please enter a valid number")
            return

        # Double confirmation for active configs
        if config_active:
            self.print_warning(f"Configuration '{config_id}' is currently active")
            self.print_warning("Deleting an active configuration will deactivate it first")
            
        self.print_warning(f"This will permanently delete configuration '{config_id}'")
        if input("Are you sure? Type 'DELETE' to confirm: ").strip() != "DELETE":
            self.print_info("Deletion cancelled")
            return

        print(f"Deleting configuration '{config_id}'...")
        response = self.make_request(
            "DELETE",
            f"{self.BASE}{config_id}?force={'true' if config_active else 'false'}",
            data={}
        )
        
        if response:
            self.print_success(f"Configuration '{config_id}' deleted successfully")
        else:
            self.print_error("Failed to delete configuration")

    def menu(self):
        """Enhanced main menu"""
        while True:
            self.print_header("WLAN Pi Network Configuration CLI")
            
            options = [
                ("View configurations", self.view_configs),
                ("Show network status", self.status),
                ("Create new configuration", self.new_config),
                ("Edit configuration", self.edit_config),
                ("Activate configuration", self.activate_config),
                ("Deactivate configuration", self.deactivate_config),
                ("Delete configuration", self.delete_config),
                ("Exit", sys.exit),
            ]
            
            print("\nAvailable Options:")
            for i, (option, _) in enumerate(options, 1):
                print(f"{i:2d}. {option}")

            try:
                choice = input(f"\nSelect option [1-{len(options)}]: ").strip()
                if not choice:
                    continue
                    
                idx = int(choice) - 1
                if idx < 0 or idx >= len(options):
                    raise ValueError("Invalid option number")
                    
                func = options[idx][1]
                print()  # Add spacing
                func()
                
                if idx < len(options) - 1:  # Not exit
                    input("\nPress Enter to continue...")
                    
            except (ValueError, KeyboardInterrupt):
                if input("\nInvalid choice or interrupted. Exit? (y/n): ").lower() == 'y':
                    sys.exit(0)
                continue
            except Exception as e:
                self.print_error(f"Unexpected error: {e}")
                if input("Continue? (y/n): ").lower() != 'y':
                    sys.exit(1)

    def main(self):
        """Enhanced main function"""
        self.print_header("WLAN Pi Core Network Configuration CLI")
        print("Advanced network configuration tool with support for:")
        print("- WPA2/WPA3 PSK and Enterprise")
        print("- 802.1X with multiple EAP methods") 
        print("- Certificate-based authentication")
        print("- OpenRoaming/Passpoint")
        print("- Network namespaces")
        print("- Monitor mode")
        
        try:
            self.get_token()
            return self.menu()
        except KeyboardInterrupt:
            print("\nOperation cancelled by user")
            sys.exit(0)
        except Exception as e:
            self.print_error(f"Fatal error: {e}")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="WLAN Pi Network Configuration CLI")
    parser.add_argument("--port", type=int, default=31415, help="API port (default: 31415)")
    args = parser.parse_args()

    try:
        cli = NetworkConfigCLI()
        cli.API_PORT = args.port
        cli.BASE = f"http://{cli.HOST}:{cli.API_PORT}/api/v1/network/config/"
        cli.main()
    except KeyboardInterrupt:
        print("\nExiting Network Configuration CLI")
        sys.exit(0)

if __name__ == "__main__":
    exit(main())

        