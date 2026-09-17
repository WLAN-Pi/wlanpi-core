import os
from pathlib import Path

# Core config
API_V1_STR: str = "/api/v1"
PROJECT_NAME: str = "wlanpi-core"
PROJECT_DESCRIPTION: str = (
    "The wlanpi-core API offers endpoints for WLAN Pi apps to get and share data. 🚀"
)

HOME_DIR = Path(os.environ.get("WLANPI_CORE_HOME_DIR", "/home/wlanpi")).expanduser()
HOME = str(HOME_DIR)
SECRETS_DIR = str(HOME_DIR / ".local/share/wlanpi-core/secrets")
ENCRYPTION_KEY_FILE = "fernet_key.b64"
SHARED_SECRET_FILE = "shared_secret.bin"
DATABASE_PATH = f"{SECRETS_DIR}/tokens.db"

# Linux programs
IFCONFIG_FILE: str = "/sbin/ifconfig"
IW_FILE: str = "/sbin/iw"
IP_FILE: str = "/usr/sbin/ip"
UFW_FILE: str = "/usr/sbin/ufw"
ETHTOOL_FILE: str = "/sbin/ethtool"
DUMPCAP_FILE: str = "/usr/bin/dumpcap"
LLDPCTL_FILE: str = "/usr/sbin/lldpctl"

# Mode changer scripts
MODE_FILE: str = "/etc/wlanpi-state"

# Version file for WLAN Pi image
WLANPI_IMAGE_FILE: str = "/etc/wlanpi-release"

WCONSOLE_SWITCHER_FILE: str = "/opt/wlanpi-wconsole/wconsole_switcher"
HOTSPOT_SWITCHER_FILE: str = "/opt/wlanpi-hotspot/hotspot_switcher"
WIPERF_SWITCHER_FILE: str = "/opt/wlanpi-wiperf/wiperf_switcher"
SERVER_SWITCHER_FILE: str = "/opt/wlanpi-server/server_switcher"
BRIDGE_SWITCHER_FILE: str = "/opt/wlanpi-bridge/bridge_switcher"

REG_DOMAIN_FILE: str = "/usr/bin/wlanpi-reg-domain"
TIME_ZONE_FILE: str = "/usr/bin/wlanpi-timezone"

# WPA Supplicant dbus service and interface
WPAS_DBUS_SERVICE: str = "fi.w1.wpa_supplicant1"
WPAS_DBUS_INTERFACE: str = "fi.w1.wpa_supplicant1"
WPAS_DBUS_OPATH: str = "/fi/w1/wpa_supplicant1"
WPAS_DBUS_INTERFACES_INTERFACE: str = "fi.w1.wpa_supplicant1.Interface"
WPAS_DBUS_INTERFACES_OPATH: str = "/fi/w1/wpa_supplicant1/Interfaces"
WPAS_DBUS_BSS_INTERFACE: str = "fi.w1.wpa_supplicant1.BSS"
WPAS_DBUS_NETWORK_INTERFACE: str = "fi.w1.wpa_supplicant1.Network"

# VLAN model constants
DEFAULT_VLAN_INTERFACE_FILE = "/etc/network/interfaces.d/vlans"
DEFAULT_INTERFACE_FILE = "/etc/network/interfaces"

# Service Constants
BT_ADAPTER = "hci0"

# Network Namespace/Config Constants
SUPPORTED_MODELS = ["M4", "M4+", "R4"]
DEFAULT_CTRL_INTERFACE = "/run/wpa_supplicant"
DEFAULT_CONFIG_DIR = "/etc/wpa_supplicant"
DEFAULT_DHCP_DIR = "/etc/network/interfaces.d"
CONFIG_DIR = str(HOME_DIR / ".local/share/wlanpi-core/netcfg/configs")
CURRENT_CONFIG_FILE = str(HOME_DIR / ".local/share/wlanpi-core/netcfg/current.txt")
PID_DIR = str(HOME_DIR / ".local/share/wlanpi-core/netcfg/pids")
APPS_FILE = str(HOME_DIR / ".local/share/wlanpi-core/netcfg/apps.json")
WPA_LOG_FILE = "/tmp/wpa.log"
CREATE_MONITOR_PAIRS_DEFAULT = True
CREATE_MONITOR_PAIRS_UNINIT = True

#### Paths below here are relative to script dir or /tmp fixed paths ###

# Networkinfo data file names
IPCONFIG_FILE: str = "/opt/wlanpi-common/networkinfo/ipconfig.sh"
REACHABILITY_FILE: str = "/opt/wlanpi-common/networkinfo/reachability.sh"
REACHABILITY_MAX_CUSTOM_TARGETS: int = 10
LIBRESPEED_CLI: str = "/usr/bin/librespeed-cli"
SPEEDTEST_TIMEOUT_SEC: int = 120
COMMAND_TIMEOUT_SEC: int = 30
PUBLICIP_CMD: str = "/opt/wlanpi-common/networkinfo/publicip.sh"
PUBLICIP6_CMD: str = "/opt/wlanpi-common/networkinfo/publicip6.sh"
BLINKER_FILE: str = "/opt/wlanpi-common/networkinfo/portblinker.sh"
HOSTAPD_CONF_FILE: str = "/etc/hostapd/hostapd.conf"
