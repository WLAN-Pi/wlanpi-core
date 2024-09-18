from collections import defaultdict
from typing import Optional, Literal, Callable

from wlanpi_core.schemas.network.network import IPInterface
from wlanpi_core.schemas.network.types import IP_SHOW_TYPES, CustomIPInterfaceFilter
from wlanpi_core.utils.general import run_command


def get_interfaces(show_type: Optional[IP_SHOW_TYPES] = None, custom_filter: Optional[CustomIPInterfaceFilter]=None ) -> list[IPInterface]:
    cmd = ["ip", "--details", "-j", "addr", "show"]
    if show_type:
        cmd += ["type", show_type.lower()]
    cmd_output = run_command(cmd).output_from_json()
    if custom_filter:
        return [j for j in [IPInterface.model_validate(i) for i in cmd_output] if custom_filter(j)]
    return [IPInterface.model_validate(i) for i in cmd_output]

def get_interfaces_by_interface(show_type: Optional[IP_SHOW_TYPES] = None, custom_filter: Optional[CustomIPInterfaceFilter]=None  ) -> dict[str, list[IPInterface]]:
    out_dict = defaultdict(list)
    for interface in get_interfaces(show_type=show_type, custom_filter=custom_filter):
        out_dict[interface.ifname].append(interface)
    return out_dict