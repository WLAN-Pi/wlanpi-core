from typing import Optional, Any

from wlanpi_core.utils.general import run_command

def get_default_gateways() -> dict[str, str]:
    """ Finds the default gateway of each interface on the system using 'ip route show'
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

def get_interface_addresses(interface: Optional[str] = None) -> dict[str, dict[str, str]]:
    res = get_interface_address_data(interface=interface)
    out_obj = {}
    for item in res:
        if item['ifname'] not in out_obj:
            out_obj[item['ifname']] = {'inet': [], 'inet6': []}
        for addr in item["addr_info"]:
            out_obj[item['ifname']][addr['family']].append(addr['local'])
    return out_obj
