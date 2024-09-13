from collections import defaultdict
from typing import Optional, Literal

from wlanpi_core.schemas.network.network import IPInterface
from wlanpi_core.schemas.network.types import IP_SHOW_TYPES
from wlanpi_core.utils.general import run_command


def get_interfaces(show_type: Optional[IP_SHOW_TYPES] = None ) -> list[IPInterface]:
    cmd = ["ip", "-j", "addr", "show"]
    if show_type:
        cmd += ["type", show_type.lower()]
    cmd_output = run_command(cmd).output_from_json()
    return [IPInterface.model_validate(i) for i in cmd_output]

def get_interfaces_by_interface(show_type: Optional[IP_SHOW_TYPES] = None ) -> dict[str, list[IPInterface]]:
    out_dict = defaultdict(list)
    for interface in get_interfaces(show_type=show_type):
        out_dict[interface.ifname].append(interface)
    return out_dict