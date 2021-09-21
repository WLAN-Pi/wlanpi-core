from shutil import which
from typing import Optional

from wlanpi_core.models.validation_error import ValidationError

from .helpers import get_phy80211_interfaces, run_cli_async


async def executable_exists(name: str) -> bool:
    """
    Check whether `name` is on PATH and marked as executable.
    """
    return which(name) is not None


async def test_wifi_interface(interface: str) -> dict:
    test = {}
    test["name"] = interface

    test["mac"] = (
        await run_cli_async(f"cat /sys/class/net/{interface}/address")
    ).strip()

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

    executable = {}
    tcpdump_exists = await executable_exists("tcpdump")
    executable["tcpdump"] = tcpdump_exists
    iw_exists = await executable_exists("iw")
    executable["iw"] = iw_exists
    ip_exists = await executable_exists("ip")
    executable["ip"] = ip_exists
    ifconfig_exists = await executable_exists("ifconfig")
    executable["ifconfig"] = ifconfig_exists
    airmonng_exists = await executable_exists("airmon-ng")
    executable["airmon-ng"] = airmonng_exists

    # add executable tests to diag
    diag["tools"] = executable

    tool_versions = {}
    if tcpdump_exists:
        tool_versions["tcpdump"] = await run_cli_async(
            "tcpdump --version", want_stderr=True
        )
    else:
        tool_versions["tcpdump"] = "unknown"

    if iw_exists:
        tool_versions["iw"] = await run_cli_async("iw --version")
    else:
        tool_versions["iw"] = "unknown"

    if ip_exists:
        tool_versions["ip"] = await run_cli_async("ip -V")
    else:
        tool_versions["ip"] = "unknown"

    if ifconfig_exists:
        tool_versions["ifconfig"] = await run_cli_async("ifconfig --version")
    else:
        tool_versions["ifconfig"] = "unknown"

    # add version tests to diag
    diag["versions"] = tool_versions

    return diag


async def get_interface_diagnostics(interface: Optional[str] = None):
    interfaces = get_phy80211_interfaces()
    results = {}
    if interface:
        if interface not in interfaces:
            raise ValidationError(
                status_code=400, error_msg=f"wlan interface {interface} not found"
            )
        results["interfaces"] = [await test_wifi_interface(interface)]
        return results
    else:
        ifaces = []
        for interface in interfaces:
            ifaces.append(await test_wifi_interface(interface))
        results["interfaces"] = ifaces
        return results
