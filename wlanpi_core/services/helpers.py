"""
shared resources between services
"""

import asyncio
import subprocess
from typing import Union

from wlanpi_core.models.runcommand_error import RunCommandError

# Linux programs
IFCONFIG_FILE = "/sbin/ifconfig"
IW_FILE = "/sbin/iw"
IP_FILE = "/usr/sbin/ip"
UFW_FILE = "/usr/sbin/ufw"
ETHTOOL_FILE = "/sbin/ethtool"

# Mode changer scripts
MODE_FILE = "/etc/wlanpi-state"

# Version file for WLAN Pi image
WLANPI_IMAGE_FILE = "/etc/wlanpi-release"

WCONSOLE_SWITCHER_FILE = "/opt/wlanpi-wconsole/wconsole_switcher"
HOTSPOT_SWITCHER_FILE = "/opt/wlanpi-hotspot/hotspot_switcher"
WIPERF_SWITCHER_FILE = "/opt/wlanpi-wiperf/wiperf_switcher"
SERVER_SWITCHER_FILE = "/opt/wlanpi-server/server_switcher"
BRIDGE_SWITCHER_FILE = "/opt/wlanpi-bridge/bridge_switcher"

REG_DOMAIN_FILE = "/usr/bin/wlanpi-reg-domain"
TIME_ZONE_FILE = "/usr/bin/wlanpi-timezone"

#### Paths below here are relative to script dir or /tmp fixed paths ###

# Networkinfo data file names
LLDPNEIGH_FILE = "/tmp/lldpneigh.txt"
CDPNEIGH_FILE = "/tmp/cdpneigh.txt"
IPCONFIG_FILE = "/opt/wlanpi-common/networkinfo/ipconfig.sh 2>/dev/null"
REACHABILITY_FILE = "/opt/wlanpi-common/networkinfo/reachability.sh"
PUBLICIP_CMD = "/opt/wlanpi-common/networkinfo/publicip.sh"
PUBLICIP6_CMD = "/opt/wlanpi-common/networkinfo/publicip6.sh"
BLINKER_FILE = "/opt/wlanpi-common/networkinfo/portblinker.sh"


async def run_cli_async(cmd: str, want_stderr: bool = False) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode == 0:
        if stdout:
            return stdout.decode()
        if stderr and want_stderr:
            return stderr.decode()

    if stderr:
        raise RunCommandError(
            return_code=424, error_msg=f"'{cmd}' gave stderr response"
        )


def run_command(cmd) -> Union[str, None]:
    """
    Runs the given command, and handles errors and formatting.
    """
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL)
        return output.decode().strip()
    except subprocess.CalledProcessError:
        return None
