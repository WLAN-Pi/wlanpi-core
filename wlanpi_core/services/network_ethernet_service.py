from typing import Optional, Union

from ..models.network import common
from ..models.network.vlan import LiveVLANs
from ..models.network.vlan.vlan_file import VLANFile
from ..schemas.network.network import IPInterface, IPInterfaceAddress
from ..schemas.network.types import CustomIPInterfaceFilter

# https://man.cx/interfaces(5)


async def get_vlans(
    interface: Optional[str] = None,
    custom_filter: Optional[CustomIPInterfaceFilter] = None,
):
    """
    Returns all VLANS configured in /etc/network/interfaces.d/vlans as objects
    """
    # vlan_file = VLANFile()
    # return vlan_file.get_vlans(interface)
    if interface is None:
        return LiveVLANs.get_vlan_interfaces_by_interface(custom_filter=custom_filter)
    else:
        return {
            interface: LiveVLANs.get_vlan_interfaces_by_interface(
                custom_filter=custom_filter
            ).get(interface, [])
        }


async def create_vlan(
    interface: str, vlan_id: Union[str, int], addresses: list[IPInterfaceAddress]
):
    """
    Creates or updates a VLAN definition for a given interface.
    """
    # vlan_file = VLANFile()
    # return vlan_file.create_update_vlan(configuration=configuration, require_existing_interface=require_existing_interface)

    return LiveVLANs.create_vlan(
        if_name=interface, vlan_id=int(vlan_id), addresses=addresses
    )


async def remove_vlan(interface: str, vlan_id: Union[str, int], allow_missing=False):
    """
    Removes a VLAN definition for a given interface.
    """
    VLANFile()
    return LiveVLANs.delete_vlan(
        if_name=interface, vlan_id=int(vlan_id), allow_missing=allow_missing
    )


async def get_interfaces(
    interface: Optional[str],
    allow_missing=False,
    custom_filter: Optional[CustomIPInterfaceFilter] = None,
) -> dict[str, list[IPInterface]]:
    """
    Returns definitions for all network interfaces known by the `ip` command.
    """
    if interface is None:
        return common.get_interfaces_by_interface(custom_filter=custom_filter)
    else:
        return {
            interface: common.get_interfaces_by_interface(
                custom_filter=custom_filter
            ).get(interface, [])
        }
