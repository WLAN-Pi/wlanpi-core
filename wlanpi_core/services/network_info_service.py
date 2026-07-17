from __future__ import annotations

import os
import re
import stat

from wlanpi_core.constants import (
    CDPNEIGH_FILE,
    ETHTOOL_FILE,
    IFCONFIG_FILE,
    IPCONFIG_FILE,
    IW_FILE,
    LLDPNEIGH_FILE,
    PUBLICIP6_CMD,
    PUBLICIP_CMD,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.core.logging import get_logger
from wlanpi_core.utils.general import run_command

log = get_logger(__name__)

_NEIGHBOUR_FILE_MAX_BYTES = 64 * 1024


def _read_neighbour_file(path: str) -> list[str] | None:
    """Read a trusted networkinfo output file without following links."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise OSError(f"refusing non-regular networkinfo file: {path}")
        if file_stat.st_uid != 0:
            raise OSError(f"refusing non-root-owned networkinfo file: {path}")
        if file_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise OSError(f"refusing writable networkinfo file: {path}")
        if file_stat.st_nlink != 1:
            raise OSError(f"refusing multiply-linked networkinfo file: {path}")
        if file_stat.st_size > _NEIGHBOUR_FILE_MAX_BYTES:
            raise OSError(f"networkinfo file is too large: {path}")

        with os.fdopen(fd, "rb", closefd=True) as file_obj:
            fd = -1
            content = file_obj.read(_NEIGHBOUR_FILE_MAX_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)

    if len(content) > _NEIGHBOUR_FILE_MAX_BYTES:
        raise OSError(f"networkinfo file is too large: {path}")

    return content.decode("utf-8", errors="replace").splitlines()


def _show_neighbour(path: str, protocol: str) -> dict:
    response = {"info": []}
    try:
        lines = _read_neighbour_file(path)
    except OSError as exc:
        log.warning("Unable to read %s neighbour data: %s", protocol, exc)
        response["error"] = f"Issue getting {protocol} neighbour"
        return response

    if not lines:
        response["error"] = "No neighbour"
        return response

    response["info"] = lines
    return response


def _section_debug_label(section: str, value) -> dict:
    """Compact shape summary for debug logs (helps UI parsing issues)."""
    if not isinstance(value, dict):
        return {"type": type(value).__name__, "value": repr(value)[:200]}
    label = {"keys": list(value.keys())}
    if "error" in value:
        label["error"] = value["error"]
    if "info" in value and isinstance(value["info"], list):
        label["info_count"] = len(value["info"])
    if section == "interfaces":
        label["interface_count"] = len([k for k in value.keys() if k != "error"])
        label["interface_names"] = [name for name in value if name != "error"][:8]
    if section == "wlan_interfaces":
        label["wlan_count"] = len(value)
        label["wlan"] = {
            name: {k: type(v).__name__ for k, v in fields.items()}
            for name, fields in list(value.items())[:8]
        }
    return label


def show_info():
    log.debug("show_info: building network info aggregate")
    output = {}

    output["interfaces"] = show_interfaces()
    log.debug("show_info: interfaces %s", _section_debug_label("interfaces", output["interfaces"]))

    output["wlan_interfaces"] = show_wlan_interfaces()
    log.debug(
        "show_info: wlan_interfaces %s",
        _section_debug_label("wlan_interfaces", output["wlan_interfaces"]),
    )

    output["eth0_ipconfig_info"] = show_eth0_ipconfig()
    log.debug(
        "show_info: eth0_ipconfig_info %s",
        _section_debug_label("eth0_ipconfig_info", output["eth0_ipconfig_info"]),
    )

    output["vlan_info"] = show_vlan()
    log.debug("show_info: vlan_info %s", _section_debug_label("vlan_info", output["vlan_info"]))

    output["lldp_neighbour_info"] = show_lldp_neighbour()
    log.debug(
        "show_info: lldp_neighbour_info %s",
        _section_debug_label("lldp_neighbour_info", output["lldp_neighbour_info"]),
    )

    output["cdp_neighbour_info"] = show_cdp_neighbour()
    log.debug(
        "show_info: cdp_neighbour_info %s",
        _section_debug_label("cdp_neighbour_info", output["cdp_neighbour_info"]),
    )

    output["public_ip"] = show_publicip()
    log.debug("show_info: public_ip %s", _section_debug_label("public_ip", output["public_ip"]))

    return output


def show_interfaces():
    """
    Return the list of network interfaces with IP address (if available)
    """

    ifconfig_file = IFCONFIG_FILE
    iw_file = IW_FILE

    interfaces = {}

    try:
        ifconfig_info = run_command([ifconfig_file, "-a"], raise_on_fail=True).stdout
    except Exception as ex:
        interfaces["error"] = "ifconfig error" + str(ex)
        return interfaces

    # Extract interface info with a bit of regex magic
    interface_re = re.findall(
        r"^(\w+?)\: flags(.*?)RX packets", ifconfig_info, re.DOTALL | re.MULTILINE
    )
    if interface_re is None:
        # Something broke is our regex - report an issue
        interfaces["error"] = "match error"
    else:
        for result in interface_re:
            # save the interface name
            interface_name = result[0]
            interfaces[interface_name] = {}

            # look at the rest of the interface info & extract IP if available
            interface_info = result[1]

            # determine interface status
            status = (
                "UP"
                if re.search("UP", interface_info, re.MULTILINE) is not None
                else "DOWN"
            )

            # determine IP address
            inet_search = re.search("inet (.+?) ", interface_info, re.MULTILINE)
            if inet_search is None:
                ip_address = "-"

                # do check if this is an interface in monitor mode
                if re.search(r"(wlan\d+)|(mon\d+)", interface_name, re.MULTILINE):
                    # fire up 'iw' for this interface (hmmm..is this a bit of an un-necessary ovehead?)
                    try:
                        iw_info = run_command(
                            [iw_file, interface_name, "info"],
                            raise_on_fail=True,
                        ).stdout

                        if re.search("type monitor", iw_info, re.MULTILINE):
                            ip_address = "Monitor"
                    except Exception:
                        ip_address = "-"
            else:
                ip_address = inet_search.group(1)

            # format interface info
            interfaces[interface_name]["status"] = status
            interfaces[interface_name]["ip"] = ip_address

    return interfaces


def channel_lookup(freq_mhz):
    """
    Converts frequency (MHz) to channel number
    """
    if freq_mhz == 2484:
        return 14
    elif 2412 <= freq_mhz <= 2484:
        return int(((freq_mhz - 2412) / 5) + 1)
    elif 5160 <= freq_mhz <= 5885:
        return int(((freq_mhz - 5180) / 5) + 36)
    elif 5955 <= freq_mhz <= 7115:
        return int(((freq_mhz - 5955) / 5) + 1)

    return None


def show_wlan_interfaces():
    """
    Create pages to summarise WLAN interface info
    """

    interfaces = []
    output = {}

    try:
        iw_dev_output = run_command([IW_FILE, "dev"]).stdout
        interfaces = [
            fields[1]
            for line in iw_dev_output.splitlines()
            if len(fields := line.strip().split()) >= 2
            and fields[0].lower() == "interface"
        ]
    except Exception:
        log.debug("Unable to enumerate WLAN interfaces", exc_info=True)

    for interface in interfaces:
        output[interface] = {}

        # Driver
        try:
            ethtool_output = run_command(
                [ETHTOOL_FILE, "-i", interface]
            ).stdout.strip()
            driver = re.search(r".*driver:\s+(.*)", ethtool_output).group(1)
            output[interface]["driver"] = driver
        except Exception:
            pass

        # Addr, SSID, Mode, Channel
        try:
            iw_output = run_command([IW_FILE, interface, "info"]).stdout.strip()
            # Addr
            try:
                addr = (
                    re.search(r".*addr\s+(.*)", iw_output)
                    .group(1)
                    .replace(":", "")
                    .upper()
                )
                output[interface]["addr"] = addr
            except Exception:
                pass

            # Mode
            try:
                mode = re.search(r".*type\s+(.*)", iw_output).group(1)
                output[interface]["mode"] = (
                    mode.capitalize() if not mode.isupper() else mode
                )
            except Exception:
                pass

            # SSID
            try:
                ssid = re.search(r".*ssid\s+(.*)", iw_output).group(1)
                output[interface]["ssid"] = ssid
            except Exception:
                pass

            # Frequency
            try:
                freq = int(
                    re.search(r".*\(([0-9]+)\s+MHz\).*", iw_output).group(1)
                )
                channel = channel_lookup(freq)
                output[interface]["freq"] = freq
                output[interface]["channel"] = channel
            except Exception:
                pass

        except Exception:
            log.debug("Unable to inspect WLAN interface %s", interface, exc_info=True)

    return output


def show_eth0_ipconfig():
    """
    Return IP configuration of eth0 including IP, default gateway, DNS servers
    """
    ipconfig_file = IPCONFIG_FILE

    eth0_ipconfig_info = {}

    try:
        ipconfig_info = run_command([ipconfig_file]).stdout.strip().split("\n")

    except RunCommandError as exc:
        eth0_ipconfig_info["error"] = (
            f"Issue getting ipconfig ({exc.return_code}): {exc.error_msg}"
        )
        return eth0_ipconfig_info
    except OSError as exc:
        eth0_ipconfig_info["error"] = f"Issue getting ipconfig: {exc}"
        return eth0_ipconfig_info

    eth0_ipconfig_info["info"] = []
    for n in ipconfig_info:
        # do some cleanup
        n = n.replace("DHCP server name", "DHCP")
        n = n.replace("DHCP server address", "DHCP IP")
        eth0_ipconfig_info["info"].append(n)

    if len(ipconfig_info) <= 1:
        eth0_ipconfig_info["error"] = "eth0 is down or not connected."
        return eth0_ipconfig_info

    return eth0_ipconfig_info


def show_vlan():
    """
    Display untagged VLAN number on eth0
    Todo: Add tagged VLAN info
    """
    vlan_info = {"info": []}

    for neighbour_file in (LLDPNEIGH_FILE, CDPNEIGH_FILE):
        try:
            lines = _read_neighbour_file(neighbour_file)
        except OSError as exc:
            log.warning("Unable to read neighbour VLAN data from %s: %s", neighbour_file, exc)
            continue

        vlan_info["info"] = [line for line in lines or [] if "VLAN" in line]
        if vlan_info["info"]:
            return vlan_info

    vlan_info["error"] = "No VLAN found"
    return vlan_info


def show_lldp_neighbour():
    """
    Display LLDP neighbour on eth0
    """
    return _show_neighbour(LLDPNEIGH_FILE, "LLDP")


def show_cdp_neighbour():
    """
    Display CDP neighbour on eth0
    """
    return _show_neighbour(CDPNEIGH_FILE, "CDP")


def show_publicip(ip_version=4):
    """
    Shows public IP address and related details, works with any interface with internet connectivity
    """

    publicip_info = {"info": []}
    cmd = PUBLICIP6_CMD if ip_version == 6 else PUBLICIP_CMD

    try:
        publicip_output = run_command(cmd).stdout.strip().split("\n")
        for line in publicip_output:
            publicip_info["info"].append(line)
    except (RunCommandError, OSError):
        publicip_info["error"] = "Failed to detect public IP address"
        return publicip_info

    return publicip_info
