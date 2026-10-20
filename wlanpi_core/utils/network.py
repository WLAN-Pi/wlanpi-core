"""Helpers for querying the network configuration."""

import re
from typing import Any

from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import netns_prefix
from wlanpi_core.utils.validation import validate_interface_name

# wpa_supplicant's printf_encode writes \\ \" \e \n \r \t and \xNN; iw's
# print_ssid_escaped writes only \xNN (a backslash becomes \x5c), so one
# decoder handles both.
_SSID_ESCAPE = re.compile(rb"\\(x[0-9a-fA-F]{2}|.)", re.DOTALL)
_SSID_CONTROL = {b"e": b"\x1b", b"n": b"\n", b"r": b"\r", b"t": b"\t"}


def _unescape_ssid_byte(match: re.Match[bytes]) -> bytes:
    token = match.group(1)
    if len(token) == 3:
        return bytes([int(token[1:], 16)])
    return _SSID_CONTROL.get(token, token)


def ssid_text(escaped: str) -> str:
    """Decode an SSID as printed by wpa_cli or iw into text.

    An SSID of only NUL bytes (a hidden network) becomes "". Bytes that are
    not valid UTF-8 come back as ``\\xNN``.
    """
    raw = _SSID_ESCAPE.sub(
        _unescape_ssid_byte, escaped.encode("utf-8", "surrogateescape")
    )
    if not raw.strip(b"\0"):
        return ""
    # ponytail: non-UTF-8 SSIDs are ambiguous with a literal "\xNN"; add a hex
    # field to ScanItem when a client needs the exact bytes.
    return raw.decode("utf-8", "backslashreplace")


def get_default_gateways(namespace: str | None = None) -> dict[str, str]:
    """Find the default gateway of each interface using 'ip route show'.

    Args:
        namespace: Network namespace to read routes from; None for root.

    Returns:
        a dictionary mapping interfaces to their default gateways.
    Raises:
        RunCommandError: If the underlying command failed.
    """

    # Execute 'ip route show' command which lists all network routes
    output = run_command(
        [*netns_prefix(namespace), "ip", "route", "show"]
    ).stdout.split("\n")

    gateways: dict[str, str] = {}
    for line in output:
        if "default via" in line:  # This is the default gateway line
            res = line.split("via ")[1].split(" dev ")
            # res[1] is e.g. "eth0 proto dhcp src 192.168.6.63 metric 100";
            # take just the interface name for callers like arping -I.
            gateways[res[1].split()[0]] = res[0].strip()
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
