from collections import defaultdict
from pprint import pp
from typing import List

from wlanpi_core.models.network.vlan.vlan_errors import VLANNotFoundError, VLANCreationError, VLANExistsError
from wlanpi_core.models.unified_result import UnifiedResult
from wlanpi_core.schemas.network.network import IPInterface, IPInterfaceAddress
from wlanpi_core.schemas.network_config import Vlan
from wlanpi_core.services.helpers import run_cli_async
from wlanpi_core.utils.general import run_command


class LiveVLANs:

    def __init__(self):
        self.vlan_interfaces_by_interface = self.get_vlan_interfaces_by_interface()

    @staticmethod
    def get_vlan_interfaces() -> list[IPInterface]:
        cmd_output = run_command("ip -j addr show type vlan".split(' ')).output_from_json()
        return [IPInterface.model_validate(i) for i in cmd_output]

    @staticmethod
    def get_vlan_interfaces_by_interface() -> dict[str, list[IPInterface]]:
        out_dict = defaultdict(list)
        for interface in LiveVLANs.get_vlan_interfaces():
            out_dict[interface.ifname].append(interface)
        return out_dict


    @staticmethod
    def check_if_vlan_exists(if_name: str, vlan_id: int) -> bool:
        cmd_output = run_command(["ip", "-j", "addr", "show", f"{if_name}.{vlan_id}"], raise_on_fail=False)
        return cmd_output.success

    @staticmethod
    # async def create_vlan(configuration: Vlan):
    def create_vlan(if_name: str, vlan_id: int, addresses: List[IPInterfaceAddress]  ):

        # Check if the VLAN already exists:
        if LiveVLANs().check_if_vlan_exists(if_name, vlan_id):
            raise VLANExistsError(f"VLAN {vlan_id} already exists on {if_name}")

        # Create the VLAN:
        try:
            command = ["ip", "link", "add", "link", str(if_name), "name", f"{if_name}.{vlan_id}", "type", "vlan", "id", str(vlan_id)]
            print(command)
            run_command(command)
        except Exception as e:
            raise VLANCreationError(f"Failed to create VLAN {vlan_id} on interface {if_name}: ") from e

        try:
            # Add addresses to the VLAN
            for address in addresses:
                extras = []
                if address.broadcast:
                    extras.extend(["broadcast", str(address.broadcast)])
                if address.anycast:
                    extras.extend(["anycast", str(address.anycast)])
                if address.scope:
                    extras.extend(["scope", str(address.scope)])

                lifetimes = []
                if address.valid_life_time:
                    lifetimes.extend(["valid_lft", str(address.valid_life_time)])
                if address.preferred_life_time:
                    lifetimes.extend(["preferred_lft", str(address.preferred_life_time)])
                run_command(["ip", "addr", "add", f"{address.local}/{address.prefixlen}", *extras, "dev", f"{if_name}.{vlan_id}", *lifetimes])

        except Exception as e:
            # If this fails in any way, we should consider creation failed and attempt to remove the VLAN.
            run_command(["ip", "link", "delete", f"{if_name}.{vlan_id}"], raise_on_fail=False)
            raise VLANCreationError(f"Failed to add addresses {address.local}/{address.prefixlen} to interface {if_name}.{vlan_id}: ") from e


    #
    #
    # @staticmethod
    # def delete_vlan(self):
    #
    #
    #
    # pass



# ip link add link eth0 name eth0.100 type vlan id 100
# ip addr add 192.168.99.200/24 dev eth0.100


# ip addr show type vlan
# sudo ip link delete eth0.100

if __name__ == '__main__':

    live_vlans = LiveVLANs()
    # pp(live_vlans)
    # https://www.reddit.com/r/learnpython/comments/66sjjm/asyncio_main_is_sync_so_how_do_i_await_anything/
    #res = asyncio.get_event_loop().run_until_complete( task )
    pp(live_vlans.check_if_vlan_exists('eth0',101))

    live_vlans.create_vlan('eth0',102, [IPInterfaceAddress.model_validate({
        "family": "inet",
        "local": "192.168.199.200",
        "prefixlen": 24,
        "scope": "global",
      })])