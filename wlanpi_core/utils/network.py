import logging
import time
from typing import Any, Optional

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
