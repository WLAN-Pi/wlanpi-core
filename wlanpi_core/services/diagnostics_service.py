import fcntl
import os
import socket
import struct
from shutil import which
from typing import List, Optional

from wlanpi_core.models.validation_error import ValidationError

from .helpers import run_cli_async


async def is_tool(name: str) -> bool:
    """
    Check whether `name` is on PATH and marked as executable.
    """
    return which(name) is not None


async def get_wifi_interfaces() -> List:
    interfaces = []
    path = "/sys/class/net"
    for net, ifaces, files in os.walk(path):
        for iface in ifaces:
            for dirpath, dirnames, filenames in os.walk(os.path.join(path, iface)):
                if "phy80211" in dirnames:
                    interfaces.append(iface)
    return interfaces


async def get_ip_address(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        return socket.inet_ntoa(
            fcntl.ioctl(
                s.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack("256s", bytes(ifname[:15], "utf-8")),
            )[20:24]
        )
    except OSError:
        return None


async def test_wifi_interface(interface: str) -> dict:
    test = {}

    test["mac"] = (
        await run_cli_async(f"cat /sys/class/net/{interface}/address")
    ).strip()

    # test["local_ip"] = await get_ip_address(interface)

    test["driver"] = (
        (await run_cli_async(f"readlink -f /sys/class/net/{interface}/device/driver"))
        .strip()
        .rsplit("/", 1)[1]
    )

    """
https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-class-net

What:		/sys/class/net/<iface>/operstate
Date:		March 2006
KernelVersion:	2.6.17
Contact:	netdev@vger.kernel.org
Description:
		Indicates the interface RFC2863 operational state as a string.

		Possible values are:

		"unknown", "notpresent", "down", "lowerlayerdown", "testing",
		"dormant", "up".
    """
    operstate = await run_cli_async(f"cat /sys/class/net/{interface}/operstate")
    test["operstate"] = operstate.strip()

    _type = await run_cli_async(f"cat /sys/class/net/{interface}/type")

    _type = int(_type)
    if _type == 1:
        test["mode"] = "managed"
    elif _type == 801:
        test["mode"] = "monitor"
    elif _type == 802:
        test["mode"] = "monitor"
    elif (
        _type == 803
    ):  # https://elixir.bootlin.com/linux/latest/source/include/uapi/linux/if_arp.h#L90
        test["mode"] = "monitor"
    else:
        test["mode"] = "unknown"

    return test


async def get_diagnostics():
    """
    Return diagnostic tests for probe
    """
    diag = {}

    regdomain = await run_cli_async("iw reg get")

    diag["regdomain"] = [line for line in regdomain.split("\n") if "country" in line]
    diag["tcpdump"] = await is_tool("tcpdump")
    diag["iw"] = await is_tool("iw")
    diag["ip"] = await is_tool("ip")
    diag["ifconfig"] = await is_tool("ifconfig")
    diag["airmon-ng"] = await is_tool("airmon-ng")

    return diag


async def get_interface_diagnostics(interface: Optional[str] = None):
    results = []
    interfaces = await get_wifi_interfaces()
    if interface:
        if interface not in interfaces:
            raise ValidationError(
                status_code=400, error_msg=f"wlan interface {interface} not found"
            )
        results.append({interface: await test_wifi_interface(interface)})
        return results
    else:
        for interface in interfaces:
            results.append({interface: await test_wifi_interface(interface)})
        return results
