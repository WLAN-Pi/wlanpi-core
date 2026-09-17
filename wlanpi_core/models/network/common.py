"""Helpers for listing interfaces via ip addr show."""

from collections import defaultdict
from typing import Any

from wlanpi_core.schemas.network.network import IPInterface
from wlanpi_core.schemas.network.types import IP_SHOW_TYPES, CustomIPInterfaceFilter
from wlanpi_core.utils.general import run_command


def get_interfaces(
    show_type: IP_SHOW_TYPES | None = None,
    custom_filter: CustomIPInterfaceFilter | None = None,
) -> list[IPInterface]:
    """Return parsed interfaces from `ip --details -j addr show`."""
    cmd = ["ip", "--details", "-j", "addr", "show"]
    if show_type:
        cmd += ["type", show_type.lower()]
    parsed = run_command(cmd).output_from_json()
    # iproute2 emits empty objects ({}) for non-matching entries when filtered
    # by type (e.g. `type vlan` on a device with no VLANs), so drop entries
    # without an ifname before touching them.
    cmd_output: list[dict[str, Any]] = (
        [i for i in parsed if isinstance(i, dict) and i.get("ifname")]
        if isinstance(parsed, list)
        else []
    )

    # Attach extra data, like link speed
    for interface in cmd_output:
        if interface["ifname"].startswith("eth"):
            interface["link_speed"] = int(
                run_command(
                    ["cat", f"/sys/class/net/{interface['ifname']}/speed"]
                ).stdout
            )

    if custom_filter:
        return [
            j
            for j in [IPInterface.model_validate(i) for i in cmd_output]
            if custom_filter(j)
        ]
    return [IPInterface.model_validate(i) for i in cmd_output]


def get_interfaces_by_interface(
    show_type: IP_SHOW_TYPES | None = None,
    custom_filter: CustomIPInterfaceFilter | None = None,
) -> dict[str, list[IPInterface]]:
    """Return interfaces grouped by interface name."""
    out_dict = defaultdict(list)
    for interface in get_interfaces(show_type=show_type, custom_filter=custom_filter):
        out_dict[interface.ifname].append(interface)
    return out_dict
