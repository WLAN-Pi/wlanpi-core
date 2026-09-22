"""Ethernet interface and VLAN management service."""

from ..models.network import common
from ..models.network.vlan import LiveVLANs
from ..models.validation_error import ValidationError
from ..schemas.network.network import IPInterface, IPInterfaceAddress
from ..schemas.network.types import CustomIPInterfaceFilter
from ..utils.validation import validate_interface_name, validate_vlan_id


def _validated_interface(interface: str) -> str:
    try:
        return validate_interface_name(interface)
    except ValueError as error:
        raise ValidationError(str(error), status_code=400) from error


def _validated_vlan_id(vlan_id: str | int) -> int:
    try:
        return validate_vlan_id(vlan_id)
    except ValueError as error:
        raise ValidationError(str(error), status_code=400) from error


# https://man.cx/interfaces(5)


async def get_vlans(
    interface: str | None = None,
    custom_filter: CustomIPInterfaceFilter | None = None,
) -> dict[str, list[IPInterface]]:
    """Return all VLANs configured on the system as objects."""
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
    interface: str, vlan_id: str | int, addresses: list[IPInterfaceAddress]
) -> None:
    """Create a VLAN definition for a given interface."""
    return LiveVLANs.create_vlan(
        if_name=_validated_interface(interface),
        vlan_id=_validated_vlan_id(vlan_id),
        addresses=addresses,
    )


async def remove_vlan(
    interface: str, vlan_id: str | int, allow_missing: bool = False
) -> None:
    """Remove a VLAN definition for a given interface."""
    return LiveVLANs.delete_vlan(
        if_name=_validated_interface(interface),
        vlan_id=_validated_vlan_id(vlan_id),
        allow_missing=allow_missing,
    )


async def get_interfaces(
    interface: str | None,
    allow_missing: bool = False,
    custom_filter: CustomIPInterfaceFilter | None = None,
) -> dict[str, list[IPInterface]]:
    """Return definitions for all network interfaces known by the `ip` command."""
    if interface is None:
        return common.get_interfaces_by_interface(custom_filter=custom_filter)
    else:
        interface = _validated_interface(interface)
        return {
            interface: common.get_interfaces_by_interface(
                custom_filter=custom_filter
            ).get(interface, [])
        }
