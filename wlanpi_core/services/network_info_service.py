from __future__ import annotations

import re

from wlanpi_core.constants import (
    ETHTOOL_FILE,
    IFCONFIG_FILE,
    IPCONFIG_FILE,
    IW_FILE,
    LLDPCTL_FILE,
    PUBLICIP6_CMD,
    PUBLICIP_CMD,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.core.logging import get_logger
from wlanpi_core.utils.general import run_command

log = get_logger(__name__)


def _lldpctl_neighbours() -> list[dict]:
    """Query lldpd for the current neighbour table, one entry per interface."""
    result = run_command([LLDPCTL_FILE, "-f", "json0"], raise_on_fail=True)
    data = result.output_from_json()
    if not isinstance(data, dict):
        raise OSError("unexpected lldpctl json0 output")

    neighbours = []
    for entry in data.get("lldp") or []:
        neighbours.extend(entry.get("interface") or [])
    return neighbours


def _json0_value(field) -> str | None:
    """First value of a json0 field (each field is a list of dicts)."""
    if field and isinstance(field, list):
        return field[0].get("value")
    return None


def _neighbour_matches(interface: dict, protocol: str) -> bool:
    # lldpd reports the source protocol as e.g. "LLDP", "CDPv1", "CDPv2"
    return str(interface.get("via", "")).upper().startswith(protocol)


def _render_neighbour(interface: dict) -> list[str]:
    """Flatten one lldpctl interface entry into legacy networkinfo lines."""
    chassis = (interface.get("chassis") or [{}])[0]
    port = (interface.get("port") or [{}])[0]

    lines = []
    name = _json0_value(chassis.get("name"))
    if name:
        lines.append(f"Name: {name}")
    port_id = _json0_value(port.get("id"))
    if port_id:
        lines.append(f"Port: {port_id}")
    port_descr = _json0_value(port.get("descr"))
    if port_descr:
        lines.append(f"Desc: {port_descr}")
    mgmt_ip = _json0_value(chassis.get("mgmt-ip"))
    if mgmt_ip:
        lines.append(f"IP: {mgmt_ip}")
    pvid = next(
        (
            vlan.get("vlan-id")
            for vlan in interface.get("vlan") or []
            if vlan.get("pvid")
        ),
        None,
    )
    if pvid:
        lines.append(f"Native VLAN: {pvid}")
    model = _json0_value(chassis.get("descr"))
    if model:
        lines.append(f"Model: {model.splitlines()[0]}")
    return lines


def _show_neighbour(protocol: str) -> dict:
    response = {"info": []}
    try:
        neighbours = _lldpctl_neighbours()
    except (RunCommandError, OSError) as exc:
        log.warning("Unable to get %s neighbour data from lldpd: %s", protocol, exc)
        response["error"] = f"Issue getting {protocol} neighbour"
        return response

    matches = [n for n in neighbours if _neighbour_matches(n, protocol)]
    for interface in matches:
        if len(matches) > 1:
            response["info"].append(f"Interface: {interface.get('name', '?')}")
        response["info"].extend(_render_neighbour(interface))

    if not response["info"]:
        response["error"] = "No neighbour"
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
    Display untagged VLAN number reported by the LLDP/CDP neighbour
    Todo: Add tagged VLAN info
    """
    vlan_info = {"info": []}

    try:
        neighbours = _lldpctl_neighbours()
    except (RunCommandError, OSError) as exc:
        log.warning("Unable to read neighbour VLAN data: %s", exc)
        neighbours = []

    for protocol in ("LLDP", "CDP"):
        vlan_info["info"] = [
            line
            for interface in neighbours
            if _neighbour_matches(interface, protocol)
            for line in _render_neighbour(interface)
            if "VLAN" in line
        ]
        if vlan_info["info"]:
            return vlan_info

    vlan_info["error"] = "No VLAN found"
    return vlan_info


def show_lldp_neighbour():
    """
    Display LLDP neighbours reported by lldpd
    """
    return _show_neighbour("LLDP")


def show_cdp_neighbour():
    """
    Display CDP neighbours reported by lldpd (requires CDP enabled via -c)
    """
    return _show_neighbour("CDP")


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
