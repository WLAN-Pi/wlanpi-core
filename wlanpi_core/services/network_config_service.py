from typing import Optional, Union
from ..models.network.vlan.vlan_file import VLANFile
from ..schemas.network_config.network_config import  Vlan

# https://man.cx/interfaces(5)


async def get_vlans(interface: Optional[str] = None):
    """
    Returns all VLANS configured in /etc/network/interfaces.d/vlans as objects
    """
    vlan_file = VLANFile()
    return vlan_file.get_vlans(interface)

async def create_update_vlan(configuration: Vlan, require_existing_interface: bool = True):
    """
    Creates or updates a VLAN definition for a given interface.
    """
    vlan_file = VLANFile()
    return vlan_file.create_update_vlan(configuration=configuration, require_existing_interface=require_existing_interface)

async def remove_vlan(interface: str, vlan_tag: Union[str,int], allow_missing=False):
    """
    Removes a VLAN definition for a given interface.
    """
    vlan_file = VLANFile()
    return vlan_file.remove_vlan(interface=interface, vlan_tag=vlan_tag, allow_missing=allow_missing)

