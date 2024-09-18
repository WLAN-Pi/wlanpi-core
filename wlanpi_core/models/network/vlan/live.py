from collections import defaultdict
from pprint import pp
from typing import List, Optional

from wlanpi_core.models.network import common
from wlanpi_core.models.network.vlan.vlan_errors import VLANCreationError, VLANExistsError, VLANDeletionError
from wlanpi_core.schemas.network.network import IPInterface, IPInterfaceAddress
from wlanpi_core.schemas.network.types import CustomIPInterfaceFilter
from wlanpi_core.utils.general import run_command


class LiveVLANs:

    def __init__(self):
        self.vlan_interfaces_by_interface = self.get_vlan_interfaces_by_interface()

    @staticmethod
    def get_vlan_interfaces(custom_filter: Optional[CustomIPInterfaceFilter] = None) -> list[IPInterface]:
        return common.get_interfaces(show_type='vlan', custom_filter=custom_filter)

    @staticmethod
    def get_vlan_interfaces_by_interface(custom_filter: Optional[CustomIPInterfaceFilter] = None) -> dict[str, list[IPInterface]]:
        out_dict = defaultdict(list)
        for interface in common.get_interfaces(show_type='vlan', custom_filter=custom_filter):
            out_dict[interface.link].append(interface)
        return out_dict


    @staticmethod
    def check_if_vlan_exists(if_name: str, vlan_id: int) -> bool:
        cmd_output = run_command(["ip", "-j", "addr", "show", f"{if_name}.{vlan_id}"], raise_on_fail=False)
        return cmd_output.success


    # @staticmethod
    # def kill_dhcp_for_vlan(if_name: str, vlan_id: int) -> None:
    #     ps_output = run_command("jc ps -aux".split(' ')).output_from_json()
    #     ps_item = next((i for i in ps_output if i["command"].startswith(f"dhcpcd: {if_name}.{vlan_id}")), None)
    #     if ps_item is not None:
    #         run_command(["kill", "-9", str(ps_item["pid"])])

    @staticmethod
    def stop_dhcp_for_vlan(if_name: str, vlan_id: int) -> bool:
        res = run_command(["dhcpcd", "-x", f"{if_name}.{vlan_id}"], raise_on_fail=False)
        return res.success

    @staticmethod
    def start_dhcp_for_vlan(if_name: str, vlan_id: int, ip_version: Optional[str]=None) -> bool:
        base_command = ["dhcpcd", "-b"]
        if ip_version == '4':
            base_command.extend(['--waitip', '4'])
        if ip_version == '6':
            base_command.extend(['--waitip', '6'])
        res = run_command([*base_command, f"{if_name}.{vlan_id}"])
        return res.success

    @staticmethod
    # async def create_vlan(configuration: Vlan):
    def create_vlan(if_name: str, vlan_id: int, addresses: List[IPInterfaceAddress]  ):

        # Check if the VLAN already exists:
        if LiveVLANs().check_if_vlan_exists(if_name, vlan_id):
            raise VLANExistsError(f"VLAN {vlan_id} already exists on {if_name}")

        # Create the VLAN:
        try:
            command = ["ip", "link", "add", "link", str(if_name), "name", f"{if_name}.{vlan_id}", "type", "vlan", "id", str(vlan_id)]
            # print(command)
            run_command(command)
        except Exception as e:
            raise VLANCreationError(f"Failed to create VLAN {vlan_id} on interface {if_name}: {str(e)}") from e

        # Try to raise the interface
        try:
            command = ["ip", "link", "set", "up", f"{if_name}.{vlan_id}"]
            # print(command)
            run_command(command)
        except Exception as e:
            raise VLANCreationError(f"Failed to raise VLAN {vlan_id} on interface {if_name}: {str(e)}") from e


        # Add addresses to the VLAN
        for address in addresses:
            try:
                extras = []
                pp(address)
                if address.dynamic:
                    if address.scope:
                        extras.extend(["scope", str(address.scope)])
                    lifetimes = []
                    if address.valid_life_time:
                        lifetimes.extend(["valid_lft", str(address.valid_life_time)])
                    if address.preferred_life_time:
                        lifetimes.extend(["preferred_lft", str(address.preferred_life_time)])
                    address.local = "0.0.0.0"
                    address.prefixlen = 24
                    run_command(["ip", "addr", "add", f"{address.local}/{address.prefixlen}", *extras, "dev",
                                 f"{if_name}.{vlan_id}", *lifetimes])
                    ip_version = None,
                    if address.family == "inet":
                        ip_version = "4"
                    if address.family == "inet6":
                        ip_version = "6"
                    LiveVLANs.start_dhcp_for_vlan(if_name, vlan_id, ip_version)
                else:
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
                raise VLANCreationError(f"Failed to add addresses {address.local}/{address.prefixlen} to interface {if_name}.{vlan_id}: {str(e)}") from e

    @staticmethod
    def delete_vlan(if_name: str, vlan_id: int, allow_missing: False):
        if allow_missing and not LiveVLANs().check_if_vlan_exists(if_name, vlan_id):
            return
        # Try to down the interface
        try:
            LiveVLANs.stop_dhcp_for_vlan(if_name, vlan_id)
            command = ["ip", "link", "set", "down", f"{if_name}.{vlan_id}"]
            # print(command)
            run_command(command)
        except Exception as e:
            raise VLANDeletionError(f"Failed to down VLAN {vlan_id} on interface {if_name}: {str(e)}") from e
        try:
            run_command(["ip", "link", "delete", f"{if_name}.{vlan_id}"])
        except Exception as e:
            raise VLANDeletionError(f"Failed to delete interface {if_name}.{vlan_id}: {str(e)}") from e



# ip link add link eth0 name eth0.100 type vlan id 100
# ip addr add 192.168.99.200/24 dev eth0.100


# ip addr show type vlan
# sudo ip link delete eth0.100

if __name__ == '__main__':

    live_vlans = LiveVLANs()
    print(live_vlans.get_vlan_interfaces())
    # pp(live_vlans)
    # https://www.reddit.com/r/learnpython/comments/66sjjm/asyncio_main_is_sync_so_how_do_i_await_anything/
    #res = asyncio.get_event_loop().run_until_complete( task )
    # test_vlan_id = 120
    # if live_vlans.check_if_vlan_exists('eth0',test_vlan_id):
    #     live_vlans.delete_vlan('eth0', test_vlan_id)
    #
    # live_vlans.create_vlan('eth0',test_vlan_id, [
    #     IPInterfaceAddress.model_validate({
    #         "family": "inet",
    #         "scope": "global",
    #         "dynamic": True,
    #     }),
    #     IPInterfaceAddress.model_validate({
    #         "family": "inet",
    #         "scope": "global",
    #         "local": "192.168.20.251",
    #         "prefixlen": 24
    #     })
    #
    # ])
    #
    # # print(live_vlans.kill_dhcp_for_vlan('eth0', test_vlan_id))