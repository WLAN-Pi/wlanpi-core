import os
import re
import subprocess

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
from wlanpi_core.utils.general import run_command


def show_info():
    output = {}

    output["interfaces"] = show_interfaces()
    output["wlan_interfaces"] = show_wlan_interfaces()
    output["eth0_ipconfig_info"] = show_eth0_ipconfig()
    output["vlan_info"] = show_vlan()
    output["lldp_neighbour_info"] = show_lldp_neighbour()
    output["cdp_neighbour_info"] = show_cdp_neighbour()
    output["public_ip"] = show_publicip()

    return output


def show_interfaces():
    """
    Return the list of network interfaces with IP address (if available)
    """

    ifconfig_file = IFCONFIG_FILE
    iw_file = IW_FILE

    interfaces = {}

    try:
        ifconfig_info = run_command(f"{ifconfig_file} -a", raise_on_fail=True).stdout
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
                            "{} {} info".format(iw_file, interface_name),
                            raise_on_fail=True,
                        ).stdout

                        if re.search("type monitor", iw_info, re.MULTILINE):
                            ip_address = "Monitor"
                    except:
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
    elif freq_mhz >= 2412 and freq_mhz <= 2484:
        return int(((freq_mhz - 2412) / 5) + 1)
    elif freq_mhz >= 5160 and freq_mhz <= 5885:
        return int(((freq_mhz - 5180) / 5) + 36)
    elif freq_mhz >= 5955 and freq_mhz <= 7115:
        return int(((freq_mhz - 5955) / 5) + 1)

    return None


def show_wlan_interfaces():
    """
    Create pages to summarise WLAN interface info
    """

    interfaces = []
    output = {}

    try:
        interfaces = run_command(
            f"{IW_FILE} dev 2>&1", shell=True, use_shlex=False
        ).grep_stdout_for_pattern(r"interface", flags=re.I, split=True)
        interfaces = map(lambda x: x.strip().split(" ")[1], interfaces)
    except Exception as e:
        print(e)

    for interface in interfaces:
        output[interface] = {}

        # Driver
        try:
            ethtool_output = run_command(
                f"{ETHTOOL_FILE} -i {interface}"
            ).stdout.strip()
            driver = re.search(".*driver:\s+(.*)", ethtool_output).group(1)
            output[interface]["driver"] = driver
        except Exception:
            pass

        # Addr, SSID, Mode, Channel
        try:
            iw_output = run_command(f"{IW_FILE} {interface} info").stdout.strip()
            # Addr
            try:
                addr = (
                    re.search(".*addr\s+(.*)", iw_output)
                    .group(1)
                    .replace(":", "")
                    .upper()
                )
                output[interface]["addr"] = addr
            except Exception:
                pass

            # Mode
            try:
                mode = re.search(".*type\s+(.*)", iw_output).group(1)
                output[interface]["mode"] = {
                    mode.capitalize() if not mode.isupper() else mode
                }
            except Exception:
                pass

            # SSID
            try:
                ssid = re.search(".*ssid\s+(.*)", iw_output).group(1)
                output[interface]["ssid"] = ssid
            except Exception:
                pass

            # Frequency
            try:
                freq = int(re.search(".*\(([0-9]+)\s+MHz\).*", iw_output).group(1))
                channel = channel_lookup(freq)
                output[interface]["freq"] = freq
                output[interface]["channel"] = channel
            except Exception:
                pass

        except Exception as e:
            print(e)

    return output


def show_eth0_ipconfig():
    """
    Return IP configuration of eth0 including IP, default gateway, DNS servers
    """
    ipconfig_file = IPCONFIG_FILE

    eth0_ipconfig_info = {}

    try:
        # Currently, ipconfig_file is a constant with a shell redirect in it, so need shell=True until it can be refactored
        ipconfig_info = (
            run_command(ipconfig_file, shell=True).stdout.strip().split("\n")
        )

    except RunCommandError as exc:
        eth0_ipconfig_info["error"] = (
            f"Issue getting ipconfig ({exc.return_code}): {exc.error_msg}"
        )
        return eth0_ipconfig_info
    except subprocess.CalledProcessError as exc:
        output = exc.output.decode()
        eth0_ipconfig_info["error"] = "Issue getting ipconfig" + str(output)
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
    lldpneigh_file = LLDPNEIGH_FILE
    cdpneigh_file = CDPNEIGH_FILE

    vlan_info = {"info": []}

    vlan_cmd = (
        "sudo grep -a VLAN " + lldpneigh_file + " || grep -a VLAN " + cdpneigh_file
    )

    if os.path.exists(lldpneigh_file):
        try:
            vlan_output = run_command(vlan_cmd, shell=True).stdout.strip().split("\n")
            for line in vlan_output:
                vlan_info["info"].append(line)

            if len(vlan_info) == 0:
                vlan_info["error"] = "No VLAN found"

        except:
            vlan_info["error"] = "No VLAN found"

    return vlan_info


def show_lldp_neighbour():
    """
    Display LLDP neighbour on eth0
    """
    lldpneigh_file = LLDPNEIGH_FILE

    neighbour_info = {"info": []}
    neighbour_cmd = "sudo cat " + lldpneigh_file

    if os.path.exists(lldpneigh_file):
        try:
            neighbour_output = run_command(neighbour_cmd).stdout.strip().split("\n")
            for line in neighbour_output:
                neighbour_info["info"].append(line)

        except RunCommandError as exc:
            neighbour_info["error"] = (
                f"Issue getting LLDP neighbour ({exc.return_code}): {exc.error_msg}"
            )
            return neighbour_info
        except subprocess.CalledProcessError as exc:
            neighbour_info["error"] = "Issue getting LLDP neighbour"
            return neighbour_info

    if len(neighbour_info) == 0:
        neighbour_info["error"] = "No neighbour"

    return neighbour_info


def show_cdp_neighbour():
    """
    Display CDP neighbour on eth0
    """
    cdpneigh_file = CDPNEIGH_FILE

    neighbour_info = {"info": []}
    neighbour_cmd = "sudo cat " + cdpneigh_file

    if os.path.exists(cdpneigh_file):
        try:
            neighbour_output = run_command(neighbour_cmd).stdout.strip().split("\n")
            for line in neighbour_output:
                neighbour_info["info"].append(line)

        except RunCommandError as exc:
            neighbour_info["error"] = (
                f"Issue getting CDP neighbour ({exc.return_code}): {exc.error_msg}"
            )
            return neighbour_info
        except subprocess.CalledProcessError as exc:
            neighbour_info["error"] = "Issue getting CDP neighbour"
            return neighbour_info

    if len(neighbour_info) == 0:
        neighbour_info["error"] = "No neighbour"

    return neighbour_info


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
    except subprocess.CalledProcessError:
        publicip_info["error"] = "Failed to detect public IP address"
        return publicip_info

    return publicip_info
