from importlib.util import find_spec
from traceback import print_exc

from .helpers import run_cli_async
from dbus import Interface, SystemBus
from dbus.exceptions import DBusException
import re

from wlanpi_core.models.validation_error import ValidationError
# https://man.cx/interfaces(5)
bus = SystemBus()
STANZA_PREFIXES = ("iface", "mapping", "auto", "allow-", "rename",  "source", "source-directory")
INET_METHODS = ("loopback", "static", "manual", "dhcp", "bootp", "tunnel", "ppp", "wvdial", "ipv4ll")

def interface_stanza(inteface_file):
    with open(inteface_file) as f:
        vals = ("iface", "mapping", "auto", "allow-", "source")
        tmp = []
        line_count = 0
        for line in f:
            line_count += 1
            if line.startswith(STANZA_PREFIXES):
                print(tmp)
                # tmp = [i for i in tmp if i[1]]
                tmp = [i for i in tmp if i]
                yield tmp
                # tmp = [[line_count, line.strip()]]
                tmp = [line.strip()]
            else:
                if line.strip().startswith('#'):
                    continue
                # tmp.append([line_count, line.strip()])
                tmp.append(line.strip())
    # tmp = [i for i in tmp if i[1]]
    tmp = [i for i in tmp if i]
    if tmp:
        yield tmp

def read_interfaces(filepath="/etc/network/interfaces"):
    # with open(filepath) as f:
    #     content = f.read().splitlines()  # Read the file and split it into lines
    return [ i for i in list(interface_stanza(filepath)) if i ]

async def get_vlans():
    # return read_interfaces('/etc/network/interfaces.d/vlans')
    raw_if_data = read_interfaces('/etc/network/interfaces.d/vlans')

    ethernet_interfaces = (await run_cli_async("ls /sys/class/net/ | grep eth")).split("\n")
    ethernet_interfaces = set([i.split('.')[0] for i in ethernet_interfaces if i])

    vlans_devices = {}

    # This likely can be abstracted up to being a standard interface parser
    for stanza in raw_if_data:

        first_line = stanza[0].strip()
        verb, device, *rest = first_line.split()
        base_device, vlan_id, = device.split('.')         # This might not be the best approach if renames get used, but it works for now

        if verb in ['source', 'source-directory']:
            continue

        # Create default objects
        if base_device not in vlans_devices:
            vlans_devices[base_device] = {}
        if vlan_id not in vlans_devices[base_device]:
            vlans_devices[base_device][vlan_id] = {
                'addresses': [],
                'selection': None,
            }
        if verb == 'iface':
            address = {
                'family': rest[0],
                'type': rest[1],
                'details': dict([i.split(' ', 1) for i in stanza[1:]])
            }
            vlans_devices[base_device][vlan_id]['addresses'].append(address)

        elif verb in ['auto', 'allow-auto']:
            vlans_devices[base_device][vlan_id]['selection'] = 'auto'
        elif verb == 'allow-hotplug':
            vlans_devices[base_device][vlan_id]['selection'] = 'allow-hotplug'
        # elif verb == 'source':
        #     pass
        # elif verb == 'source-directory':
        #     pass

    # vlan_raw_devices = []
    #
    # for stanza in raw_if_data:
    #     for line in stanza:
    #         verb, value = line.strip().split()
    #         if verb == 'vlan-raw-device':
    #             vlan_raw_devices.append(value)


    # for stanza in raw_if_data:
    #
    #     first_line = stanza[0][1].strip()
    #     if first_line.startswith('iface'):
    #         pass
    #     elif first_line.startswith('auto'):
    #         pass
    #     elif first_line.startswith('allow-'):
    #         pass
    #     elif first_line.startswith('source'):
    #         pass
    #     elif first_line.startswith('source-directory'):
    #         pass



    # adapter_config =

    return_obj = []

    for device, details in vlans_devices.items():
        for vlan, vlan_details in details.items():
            obj = {
                "interface": device,
                "vlan_tag": vlan,
                "addresses": [],
                "if_control": vlan_details['selection']
                # "dhcp": vlan_details['type']
            }

            for address in vlan_details["addresses"]:
                address_obj = {
                    "family": address["family"],
                    "type": 'st'
                }
                pass

            return_obj.append(obj)

    return return_obj
