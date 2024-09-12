from typing import Optional, Union

from ..models.network.vlan import LiveVLANs
from ..models.network.vlan.vlan_file import VLANFile
from ..schemas.network.network import IPInterfaceAddress
from ..schemas.network_config.network_config import  Vlan

# https://man.cx/interfaces(5)


async def get_vlans(interface: Optional[str] = None):
    """
    Returns all VLANS configured in /etc/network/interfaces.d/vlans as objects
    """
    # vlan_file = VLANFile()
    # return vlan_file.get_vlans(interface)
    if interface is None:
        return LiveVLANs.get_vlan_interfaces_by_interface()
    else:
        return LiveVLANs.get_vlan_interfaces_by_interface().get(interface, {})

async def create_vlan(interface: str, vlan_id: Union[str,int], addresses: list[IPInterfaceAddress]):
    """
    Creates or updates a VLAN definition for a given interface.
    """
    # vlan_file = VLANFile()
    # return vlan_file.create_update_vlan(configuration=configuration, require_existing_interface=require_existing_interface)

    return LiveVLANs.create_vlan(if_name=interface, vlan_id=int(vlan_id), addresses=addresses)

async def remove_vlan(interface: str, vlan_id: Union[str,int], allow_missing=False):
    """
    Removes a VLAN definition for a given interface.
    """
    vlan_file = VLANFile()
    return LiveVLANs.delete_vlan(if_name=interface, vlan_id=int(vlan_id), allow_missing=allow_missing)

