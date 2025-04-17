# Core config
API_V1_STR: str = "/api/v1"
PROJECT_NAME: str = "wlanpi-core"
PROJECT_DESCRIPTION: str = (
    "The wlanpi-core API offers endpoints for WLAN Pi apps to get and share data. 🚀"
)

SECRETS_DIR = "/home/wlanpi/.local/share/wlanpi-core/secrets"
ENCRYPTION_KEY_FILE = "fernet_key.b64"
SHARED_SECRET_FILE = "shared_secret.bin"
DATABASE_PATH = f"{SECRETS_DIR}/tokens.db"

# Linux programs
IFCONFIG_FILE: str = "/sbin/ifconfig"
IW_FILE: str = "/sbin/iw"
IP_FILE: str = "/usr/sbin/ip"
UFW_FILE: str = "/usr/sbin/ufw"
ETHTOOL_FILE: str = "/sbin/ethtool"

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

#### Paths below here are relative to script dir or /tmp fixed paths ###

# Networkinfo data file names
LLDPNEIGH_FILE: str = "/tmp/lldpneigh.txt"
CDPNEIGH_FILE: str = "/tmp/cdpneigh.txt"
IPCONFIG_FILE: str = "/opt/wlanpi-common/networkinfo/ipconfig.sh 2>/dev/null"
REACHABILITY_FILE: str = "/opt/wlanpi-common/networkinfo/reachability.sh"
PUBLICIP_CMD: str = "/opt/wlanpi-common/networkinfo/publicip.sh"
PUBLICIP6_CMD: str = "/opt/wlanpi-common/networkinfo/publicip6.sh"
BLINKER_FILE: str = "/opt/wlanpi-common/networkinfo/portblinker.sh"
