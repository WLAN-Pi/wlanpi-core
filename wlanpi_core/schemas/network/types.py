from typing import Callable, Literal

from wlanpi_core.schemas.network.network import IPInterface

IP_SHOW_TYPES = Literal[
    "vlan",
    "veth",
    "vcan",
    "vxcan",
    "dummy",
    "ifb",
    "macvlan",
    "macvtap",
    "bridge",
    "bond",
    "ipoib",
    "ip6tnl",
    "ipip",
    "sit",
    "vxlan",
    "lowpan",
    "gre",
    "gretap",
    "erspan",
    "ip6gre",
    "ip6gretap",
    "ip6erspan",
    "vti",
    "nlmon",
    "can",
    "bond_slave",
    "ipvlan",
    "geneve",
    "bridge_slave",
    "hsr",
    "macsec",
    "netdevsim",
]

CustomIPInterfaceFilter = Callable[[IPInterface], bool]
