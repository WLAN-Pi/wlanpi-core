from collections import defaultdict
from importlib.util import find_spec
from traceback import print_exc
from pprint import pp
from typing import Optional, Union

from .helpers import run_cli_async
from dbus import Interface, SystemBus
from dbus.exceptions import DBusException
import re

from wlanpi_core.models.validation_error import ValidationError
from ..schemas.network_config.network_config import NETWORK_ADDRESS_TYPES, Vlan, InetDhcpNetworkAddress

# https://man.cx/interfaces(5)
bus = SystemBus()
STANZA_PREFIXES = ("iface", "mapping", "auto", "allow-hotplug", "allow-auto", "rename",  "source", "source-directory")
INET_METHODS = ("loopback", "static", "manual", "dhcp", "bootp", "tunnel", "ppp", "wvdial", "ipv4ll")
VLAN_INTERFACE_FILE = '/etc/network/interfaces.d/vlans'

def interface_stanza(filelike):
    tmp = []
    line_count = 0
    for line in filelike:
        line_count += 1
        if line.startswith(STANZA_PREFIXES):
            # Filter out blank items
            tmp = [i for i in tmp if i]
            yield tmp
            tmp = [line.strip()]
        else:
            if line.strip().startswith('#'):
                continue
            tmp.append(line.strip())

    tmp = [i for i in tmp if i]
    if tmp:
        yield tmp

def read_interfaces(filepath="/etc/network/interfaces"):
    with open(filepath) as f:
        return [ i for i in list(interface_stanza(f)) if i ]

async def get_vlans(interface: Optional[str] = None):
    """
    Returns all VLANS configured in /etc/network/interfaces.d/vlans as objects
    """
    raw_if_data = read_interfaces(VLAN_INTERFACE_FILE)

    # Create default objects
    vlans_devices = defaultdict(lambda: defaultdict(lambda: {
                'addresses': [],
                'selection': None,
            }))

    # This likely can be abstracted up to being a standard interface parser
    for stanza in raw_if_data:

        first_line = stanza[0].strip()
        verb, device, *rest = first_line.split()
        # This might not be the best approach if renames get used, but it works for now
        base_device, vlan_id, = device.split('.')

        if verb in ['source', 'source-directory']:
            # TODO: Should we throw here? We won't be creating these but someone else might add them?
            continue

        if verb == 'iface':
            address = {
                'family': rest[0],
                'address_type': rest[1],
                'details': dict([i.split(' ', 1) for i in stanza[1:]])
            }
            vlans_devices[base_device][vlan_id]['addresses'].append(address)

        elif verb in ['auto', 'allow-auto']:
            vlans_devices[base_device][vlan_id]['selection'] = 'auto'
        elif verb == 'allow-hotplug':
            vlans_devices[base_device][vlan_id]['selection'] = 'allow-hotplug'

    return_obj = []

    for device, details in vlans_devices.items():
        if interface is not None and interface != device:
            continue
        for vlan, vlan_details in details.items():
            obj = {
                "interface": device,
                "vlan_tag": vlan,
                "addresses": [],
                "if_control": vlan_details['selection']
            }

            # There can be multiple addresses assigned to a specific VLAN interface--get them all
            for address in vlan_details["addresses"]:
                address_obj = {
                    "family": address["family"],
                    "address_type": address["address_type"],
                    **address["details"]
                }
                obj["addresses"].append(address_obj)
            return_obj.append(obj)

    return return_obj


def generate_if_config_from_object(configuration: Vlan):
    """
    Generates an /etc/network/interfaces style config string from a Vlan object
    """
    vlan_interface = f"{configuration.interface}.{configuration.vlan_tag}"
    config_string = f"{configuration.if_control} {vlan_interface}\n"

    for address_config in configuration.addresses:
        address_config_string = f"iface {vlan_interface} {address_config.family} {address_config.address_type}\n"
        pp([*address_config.model_fields.keys(), *address_config.model_extra.keys()])
        for key in [*address_config.model_fields.keys(), *address_config.model_extra.keys()]:
            # Skip null keys, as well as keys that are used for the data but not actually valid interface config
            if key in ['family', 'address_type'] or getattr(address_config, key) is None:
                continue
            # print(key)
            address_config_string += f"\t{address_config.model_fields[key].serialization_alias or key} {getattr(address_config, key)}\n"
        config_string += address_config_string
        # TODO: Possibly validate details in here.
    return config_string

async def create_update_vlan(configuration: Vlan, require_existing_interface: bool = True):
    """
    Creates or updates a VLAN definition for a given interface.
    """

    # Validate that the requested interface exists
    ethernet_interfaces = (await run_cli_async("ls /sys/class/net/ | grep eth")).split("\n")
    ethernet_interfaces = set([i.split('.')[0] for i in ethernet_interfaces if i])
    if require_existing_interface and configuration.interface not in ethernet_interfaces:
        raise ValidationError(
            f"Interface {configuration.interface} does not exist", status_code=400
        )

    # Get existing vlans:
    existing_vlans = await get_vlans()

    # If there's not already a vlan-raw-device set, set it for each address
    for address in configuration.addresses:
        if address.vlan_raw_device is None:
            address.vlan_raw_device = configuration.interface
            # address['vlan-raw-device'] = configuration.interface


    # Dump the given VLAN configuration to a basic dict to match the output of get_vlans
    config_obj = configuration.model_dump(
                by_alias=True,
                exclude_unset=True,
                exclude_none=True
            )



    pp(config_obj)
    # Scan existing to find a matching interface:
    output_vlans = []
    replaced = False
    for existing_vlan in existing_vlans:
        # If the right interface
        if existing_vlan['interface'] == configuration.interface and str(existing_vlan['vlan_tag']) == str(configuration.vlan_tag):
            # No sophisticated replace logic, just dumb swap for now.
            output_vlans.append(config_obj)
            replaced = True
        else:
            output_vlans.append(existing_vlan)
    if not replaced:
        output_vlans.append(config_obj)
    pp(output_vlans)
    output_string = '\n'.join(map(lambda f: generate_if_config_from_object(Vlan.model_validate(f)), output_vlans))

    with open(VLAN_INTERFACE_FILE, 'w') as interface_file:
        interface_file.write(output_string)

    return {
        'success': True,
        'result': output_vlans,
        'errors': {}
    }

async def remove_vlan(interface: str, vlan_tag: Union[str,int], allow_missing=False):
    """
    Removes a VLAN definition for a given interface.
    """

    # Get existing vlans:
    existing_vlans = await get_vlans()

    # Scan existing to find a matching interface:
    output_vlans = []
    removed = False
    for existing_vlan in existing_vlans:
        # If the right interface
        if existing_vlan['interface'] == interface and str(existing_vlan['vlan_tag']) == str(
                vlan_tag):
            # Just drop the entire entry.
            removed = True
            continue
        else:
            output_vlans.append(existing_vlan)
    if not removed:
        # TODO: is this really a validation error?
        raise ValidationError(
            f"Interface {interface} with VLAN {vlan_tag} does not exist", status_code=400
        )

    output_string = '\n'.join(map(lambda f: generate_if_config_from_object(Vlan.model_validate(f)), output_vlans))

    with open(VLAN_INTERFACE_FILE, 'w') as interface_file:
        interface_file.write(output_string)

    return {
        'success': True,
        'result': output_vlans,
        'errors': {}
    }

