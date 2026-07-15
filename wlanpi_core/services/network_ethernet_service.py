from typing import Optional, Union

from ..models.network import common
from ..models.network.vlan import LiveVLANs
from ..models.network.vlan.vlan_file import VLANFile
from ..schemas.network.network import IPInterfaceAddress
from ..schemas.network.types import CustomIPInterfaceFilter
from ..models.validation_error import ValidationError
from ..utils.validation import validate_interface_name, validate_vlan_id


def _validated_interface(interface: str) -> str:
    try:
        return validate_interface_name(interface)
    except ValueError as error:
        raise ValidationError(str(error), status_code=400) from error


def _validated_vlan_id(vlan_id: Union[str, int]) -> int:
    try:
        return validate_vlan_id(vlan_id)
    except ValueError as error:
        raise ValidationError(str(error), status_code=400) from error


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
        interface = _validated_interface(interface)
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
        if_name=_validated_interface(interface),
        vlan_id=_validated_vlan_id(vlan_id),
        addresses=addresses,
    )


async def remove_vlan(interface: str, vlan_id: Union[str, int], allow_missing=False):
    """
    Removes a VLAN definition for a given interface.
    """
    VLANFile()
    return LiveVLANs.delete_vlan(
        if_name=_validated_interface(interface),
        vlan_id=_validated_vlan_id(vlan_id),
        allow_missing=allow_missing,
    )


async def get_interfaces(
    interface: str,
    allow_missing=False,
    custom_filter: Optional[CustomIPInterfaceFilter] = None,
):
    """
    Returns definitions for all network interfaces known by the `ip` command.
    """
    if interface is None:
        return common.get_interfaces_by_interface(custom_filter=custom_filter)
    else:
        interface = _validated_interface(interface)
        return {
            interface: common.get_interfaces_by_interface(
                custom_filter=custom_filter
            ).get(interface, [])
        }
