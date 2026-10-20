"""Helpers for listing interfaces via ip addr show."""

import logging
import subprocess
from collections import defaultdict
from typing import Any

from wlanpi_core.adapters import discovery
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.schemas.network.network import IPInterface
from wlanpi_core.schemas.network.types import IP_SHOW_TYPES, CustomIPInterfaceFilter
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def get_interfaces(
    show_type: IP_SHOW_TYPES | None = None,
    custom_filter: CustomIPInterfaceFilter | None = None,
) -> list[IPInterface]:
    """Return parsed interfaces from `ip --details -j addr show`."""
    cmd = ["ip", "--details", "-j", "addr", "show"]
    if show_type:
        cmd += ["type", show_type.lower()]
    parsed = run_command(cmd).output_from_json()
    # iproute2 emits {} for non-matching entries when filtered by type.
    cmd_output: list[dict[str, Any]] = (
        [i for i in parsed if isinstance(i, dict) and i.get("ifname")]
        if isinstance(parsed, list)
        else []
    )

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
    namespaced: bool = False,
) -> dict[str, list[IPInterface]]:
    """Return interfaces grouped by name.

    With ``namespaced``, also include wireless interfaces in named namespaces.
    """
    out_dict = defaultdict(list)
    for interface in get_interfaces(show_type=show_type, custom_filter=custom_filter):
        out_dict[interface.ifname].append(interface)
    if not namespaced:
        return out_dict
    for live in discovery.list_namespaced_interfaces():
        try:
            parsed = ns_exec(
                ["ip", "--details", "-j", "addr", "show", "dev", live.name],
                namespace=live.netns,
                no_output=True,
            ).output_from_json()
            entries = [
                IPInterface.model_validate({**entry, "namespace": live.netns})
                for entry in (parsed if isinstance(parsed, list) else [])
                if isinstance(entry, dict) and entry.get("ifname")
            ]
        except (RunCommandError, subprocess.TimeoutExpired, ValueError) as exc:
            log.warning(f"Could not read {live.name} in {live.netns}: {exc}")
            continue
        for interface in entries:
            if custom_filter is None or custom_filter(interface):
                out_dict[interface.ifname].append(interface)
    return out_dict
