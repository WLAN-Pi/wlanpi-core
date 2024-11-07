import json
import logging
import re
import time
from collections import deque
from typing import Any, Optional, Union

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command


def get_default_gateways() -> dict[str, str]:
    """Finds the default gateway of each interface on the system using 'ip route show'
    Returns:
        a dictionary mapping interfaces to their default gateways.
    Raises:
        RunCommandError: If the underlying command failed.
    """

    # Execute 'ip route show' command which lists all network routes
    output = run_command("ip route show").stdout.split("\n")

    gateways: dict[str, str] = {}
    for line in output:
        if "default via" in line:  # This is the default gateway line
            res = line.split("via ")[1].split(" dev ")
            gateways[res[1].strip()] = res[0].strip()
    return gateways


def trace_route(target: str) -> dict[str, Any]:
    # Execute 'ip route show' command which lists all network routes
    output = run_command(["jc", "traceroute", target]).output_from_json()
    return output


def get_interface_address_data(interface: Optional[str] = None) -> list[dict[str, Any]]:
    cmd: list[str] = "ip -j addr show".split(" ")
    if interface is not None and interface.strip() != "":
        cmd.append(interface.strip())
    result = run_command(cmd).output_from_json()
    return result


def get_interface_addresses(
    interface: Optional[str] = None,
) -> dict[str, dict[str, list[str]]]:
    res = get_interface_address_data(interface=interface)
    out_obj = {}
    for item in res:
        if item["ifname"] not in out_obj:
            ifname: str = item["ifname"]
            out_obj[ifname] = {"inet": [], "inet6": []}
        for addr in item["addr_info"]:
            ifname: str = item["ifname"]
            out_obj[ifname][addr["family"]].append(addr["local"])
    return out_obj


def get_ip_address(interface):
    """
    Extract the IPv4 IP Address from the linux ip add show <if> command
    """
    try:
        res = get_interface_addresses(interface)[interface]["inet"]
        if len(res):
            return res[0]
        return None
    except RunCommandError as err:
        logging.warning(
            f"Failed to get IP address. Code:{err.return_code}, Error: {err.error_msg}"
        )
        return None


def renew_dhcp(interface) -> None:
    """
    Uses dhclient to release and request a new DHCP lease
    """
    try:
        # Release the current DHCP lease
        run_command(["sudo", "dhclient", "-r", interface], raise_on_fail=True)
        time.sleep(3)
        # Obtain a new DHCP lease
        run_command(["sudo", "dhclient", interface], raise_on_fail=True)
    except RunCommandError as err:
        logging.warning(
            f"Failed to renew DHCP. Code:{err.return_code}, Error: {err.error_msg}"
        )
        return None


class WlanChannelInfo:
    def __init__(
        self,
        band,
        frequency,
        channel_number,
        max_tx_power,
        channel_widths,
        disabled=False,
        radar_detection=False,
        dfs_state=None,
        dfs_cac_time=None,
        no_ir=False,
    ):
        self.band = band
        self.frequency = frequency
        self.channel_number = channel_number
        self.max_tx_power = max_tx_power
        self.channel_widths = channel_widths
        self.disabled = disabled
        self.radar_detection = radar_detection
        self.dfs_state = dfs_state
        self.dfs_cac_time = dfs_cac_time
        self.no_ir = no_ir

    def __repr__(self):
        return f"Band {self.band}: {self.frequency} MHz [{self.channel_number}]"

    def to_json(self):
        """Returns a JSON representation of the channel information."""
        return json.dumps(self.__dict__, indent=2)  # Use __dict__ to get all attributes


def parse_iw_phy_output(output):
    """Parses the output of 'iw phy <phy> channels' into a list of ChannelInfo objects."""

    channels = []
    current_band = None
    for line in output.splitlines():
        line = line.strip()

        if line.startswith("Band"):
            current_band = int(line.split(":")[0].split()[1])
            continue

        if line.startswith("*"):
            match = re.match(r"\* (\d+) MHz \[(\d+)\](?: \((.*?)\))?", line)
            if match:
                frequency = int(match.group(1))
                channel_number = int(match.group(2))
                disabled = False
                if match.group(3) and "disabled" in match.group(3):
                    disabled = True

                channel_info = WlanChannelInfo(
                    current_band, frequency, channel_number, None, [], disabled
                )

                channels.append(channel_info)
            continue

        if "Maximum TX power:" in line:
            channels[-1].max_tx_power = float(line.split(":")[1].strip().split()[0])
        if "Channel widths:" in line:
            channels[-1].channel_widths = line.split(":")[1].strip().split()
        if "Radar detection" in line:
            channels[-1].radar_detection = True
        if "DFS state:" in line:
            channels[-1].dfs_state = line.split(":")[1].strip()
        if "DFS CAC time:" in line:
            channels[-1].dfs_cac_time = int(line.split(":")[1].strip().split()[0])
        if "No IR" in line:
            channels[-1].no_ir = True

    return channels


def get_interface_phy_num(interface: str) -> Optional[int]:
    lines = run_command(["iw", "dev", interface, "info"]).grep_stdout_for_string(
        "wiphy", split=True
    )
    if lines:
        return int(lines[0].strip().split(" ")[1])
    return None


def get_phy_interface_name(phy_num: int) -> Optional[str]:
    res = run_command(
        ["ls", f"/sys/class/ieee80211/phy{phy_num}/device/net/"], raise_on_fail=False
    )
    if res.success:
        return res.stdout.strip()
    else:
        return None


def list_wlan_interfaces() -> list[str]:
    return run_command(  # type: ignore
        ["ls", "-1", "/sys/class/ieee80211/*/device/net/"], use_shlex=False, shell=True
    ).grep_stdout_for_pattern(r"^$|/", negate=True, split=True)


def list_ethernet_interfaces() -> list[str]:
    res = run_command(  # type: ignore
        ["ls", "-1", "/sys/class/net/*/device/net/"], use_shlex=False, shell=True
    ).grep_stdout_for_pattern(r"^$|/", negate=True, split=True)
    return [x for x in res if "eth" in x]


def get_wlan_channels(interface: str) -> list[WlanChannelInfo]:
    phy = get_interface_phy_num(interface)
    if phy is None:
        return []
    return parse_iw_phy_output(
        run_command(["iw", "phy", f"phy{phy}", "channels"]).stdout
    )


def parse_indented_output(lines: Union[str, list]):
    """Parses command output based on indentation, creating nested dicts/lists."""

    def process_lines(lines_deque: deque[str], current_indent=0) -> Union[dict, list]:
        """Recursively processes lines based on indentation."""
        pairs = []

        while len(lines_deque):
            # Bail out if the next line is a higher level.
            next_indent = len(lines_deque[0]) - len(lines_deque[0].lstrip())
            if next_indent < current_indent:
                break
            if next_indent == current_indent:
                line = lines_deque.popleft()
                next_indent = len(lines_deque) and len(lines_deque[0]) - len(
                    lines_deque[0].lstrip()
                )
                if next_indent > current_indent:
                    # This line has a sublevel, so we recurse to get the value.
                    sub_result = process_lines(lines_deque, next_indent)
                    pairs.append([line.strip(), sub_result])
                else:
                    pairs.append([line.strip(), None])
        return dict(pairs)

    if lines is str:
        lines = lines.split("\n")
    return process_lines(deque(lines))


def parse_iw_list(lines: Union[str, list]):
    """Parses iw list output based on indentation, creating nested dicts/lists."""

    def process_lines(lines_deque: deque[str], current_indent=0) -> Union[dict, list]:
        """Recursively processes lines based on indentation."""
        pairs = []

        while len(lines_deque):
            # Bail out if the next line is a higher level.
            next_indent = len(lines_deque[0]) - len(lines_deque[0].lstrip())
            if next_indent < current_indent:
                break
            if next_indent == current_indent:
                line = lines_deque.popleft()
                # Handle an annoying multiline output case
                if line.lstrip().startswith("*"):
                    while len(lines_deque) and (
                        len(lines_deque[0]) - len(lines_deque[0].lstrip())
                        > current_indent
                    ):
                        if not lines_deque[0].strip().startswith("*"):
                            line += " " + lines_deque.popleft().strip()

                next_indent = len(lines_deque) and len(lines_deque[0]) - len(
                    lines_deque[0].lstrip()
                )
                if next_indent > current_indent:
                    # This line has a sublevel, so we recurse to get the value.
                    sub_result = process_lines(lines_deque, next_indent)
                    pairs.append([line.strip(), sub_result])
                else:
                    pairs.append([line.strip(), None])

        # Detect dict-like structure
        if any(
            ": " in pair[0] or pair[0].rstrip().endswith(":") or pair[1] is not None
            for pair in pairs
        ):
            data = {"flags": []}
            for pair in pairs:
                pair[0] = pair[0].lstrip("*").lstrip()
                # We already have key-value data, so it must be a pair.
                if pair[1] is not None:
                    data[pair[0].rstrip(":")] = pair[1]
                elif ": " in pair[0]:
                    key, value = pair[0].split(": ", maxsplit=1)
                    if value:
                        data[key] = value.strip()
                else:
                    data["flags"].append(pair[0])
            return data
        # Almost definitely a list
        else:
            return [pair[0].lstrip("*").lstrip() for pair in pairs]

    if lines is str:
        lines = lines.split("\n")
    return process_lines(deque(lines))


def get_interface_details(
    interface: Optional[str] = None,
) -> Optional[dict[str, dict[str, any]]]:
    if interface:
        phy_num = get_interface_phy_num(interface=interface)
        if phy_num is None:
            return None
        iw_list_data = parse_iw_list(
            run_command(["iw", "phy", f"phy{phy_num}", "info"]).stdout.split("\n")
        )
    else:
        iw_list_data = parse_iw_list(run_command(["iw", "list"]).stdout.split("\n"))

    return {
        get_phy_interface_name(k.split(" ")[1].split("phy")[1]): {
            "phy_name": k.split(" ")[1],
            "mac": get_interface_mac(
                get_phy_interface_name(k.split(" ")[1].split("phy")[1])
            ),
            "details": v,
        }
        for k, v in iw_list_data.items()
        if "phy" in k
    }


def get_interface_mac(interface: str) -> str:
    return run_command(["jc", "ifconfig", interface]).output_from_json()[0]["mac_addr"]


if __name__ == "__main__":
    print(list_wlan_interfaces())
