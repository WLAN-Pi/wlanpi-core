"""Helpers for querying the network configuration."""

from typing import Any

from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.validation import validate_interface_name


def get_default_gateways() -> dict[str, str]:
    """Find the default gateway of each interface using 'ip route show'.

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


def get_interface_address_data(interface: str | None = None) -> list[dict[str, Any]]:
    """Return parsed `ip -j addr show` output for one or all interfaces."""
    cmd: list[str] = "ip -j addr show".split(" ")
    if interface is not None and interface.strip() != "":
        cmd.append(validate_interface_name(interface.strip()))
    result = run_command(cmd).output_from_json()
    return result if isinstance(result, list) else []


def get_interface_addresses(
    interface: str | None = None,
) -> dict[str, dict[str, str]]:
    """Return interface addresses grouped by interface and address family."""
    res = get_interface_address_data(interface=interface)
    out_obj: dict[str, dict[str, Any]] = {}
    for item in res:
        if item["ifname"] not in out_obj:
            out_obj[item["ifname"]] = {"inet": [], "inet6": []}
        for addr in item["addr_info"]:
            out_obj[item["ifname"]][addr["family"]].append(addr["local"])
    return out_obj
