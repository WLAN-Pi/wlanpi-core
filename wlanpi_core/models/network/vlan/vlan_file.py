from collections import defaultdict
from typing import Optional, Union

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.network.config import Vlan
from wlanpi_core.services.helpers import run_cli_async


class VLANFile:
    STANZA_PREFIXES = (
        "iface",
        "mapping",
        "auto",
        "allow-hotplug",
        "allow-auto",
        "rename",
        "source",
        "source-directory",
    )
    INET_METHODS = (
        "loopback",
        "static",
        "manual",
        "dhcp",
        "bootp",
        "tunnel",
        "ppp",
        "wvdial",
        "ipv4ll",
    )
    DEFAULT_VLAN_INTERFACE_FILE = "/etc/network/interfaces.d/vlans"
    DEFAULT_INTERFACE_FILE = "/etc/network/interfaces"

    def __init__(
        self,
        interface_file: str = DEFAULT_INTERFACE_FILE,
        vlan_interface_file: str = DEFAULT_VLAN_INTERFACE_FILE,
    ):
        self.vlans = []
        self.interface_file = interface_file
        self.vlan_interface_file = vlan_interface_file

        self.reload_vlans_file()

    @classmethod
    def get_interface_stanzas(cls, filelike):
        """Gets the interface stanzas from a interfaces-like file"""
        tmp = []
        line_count = 0
        for line in filelike:
            line_count += 1
            if line.startswith(cls.STANZA_PREFIXES):
                # Filter out blank items
                tmp = [i for i in tmp if i]
                yield tmp
                tmp = [line.strip()]
            else:
                if line.strip().startswith("#"):
                    continue
                tmp.append(line.strip())

        tmp = [i for i in tmp if i]
        if tmp:
            yield tmp

    def read_interfaces_file(self, filepath: Optional[str] = None):
        """
        Reads the interfaces file and returns a list of interface stanzas.
        """
        if filepath is None:
            filepath = self.interface_file
        with open(filepath) as f:
            return [i for i in list(self.get_interface_stanzas(f)) if i]

    def get_vlans(self, interface: Optional[str] = None) -> list:
        """
        Returns all VLANS configured in the configured interface file as objects
        """
        raw_if_data = self.read_interfaces_file(self.vlan_interface_file)

        # Create default objects
        vlans_devices: dict[str, dict[str, any]] = defaultdict(
            lambda: defaultdict(
                lambda: {
                    "addresses": [],
                    "selection": None,
                }
            )
        )

        # This likely can be abstracted up to being a standard interface parser
        for stanza in raw_if_data:

            first_line = stanza[0].strip()
            verb, device, *rest = first_line.split()
            # This might not be the best approach if renames get used, but it works for now
            (
                base_device,
                vlan_id,
            ) = device.split(".")

            if verb in ["source", "source-directory"]:
                # TODO: Should we throw here? We won't be creating these but someone else might add them?
                continue

            if verb == "iface":
                address = {
                    "family": rest[0],
                    "address_type": rest[1],
                    "details": dict([i.split(" ", 1) for i in stanza[1:]]),
                }
                vlans_devices[base_device][vlan_id]["addresses"].append(address)

            elif verb in ["auto", "allow-auto"]:
                vlans_devices[base_device][vlan_id]["selection"] = "auto"
            elif verb == "allow-hotplug":
                vlans_devices[base_device][vlan_id]["selection"] = "allow-hotplug"

        return_obj = []

        for device, details in vlans_devices.items():
            if interface is not None and interface != device:
                continue
            for vlan, vlan_details in details.items():
                obj = {
                    "interface": device,
                    "vlan_tag": vlan,
                    "addresses": [],
                    "if_control": vlan_details["selection"],
                }

                # There can be multiple addresses assigned to a specific VLAN interface--get them all
                for address in vlan_details["addresses"]:
                    address_obj = {
                        "family": address["family"],
                        "address_type": address["address_type"],
                        **address["details"],
                    }
                    obj["addresses"].append(address_obj)
                return_obj.append(obj)

        return return_obj

    def reload_vlans_file(self) -> None:
        self.vlans = self.get_vlans()

    @staticmethod
    def generate_if_config_from_object(configuration: Vlan) -> str:
        """
        Generates an /etc/network/interfaces style config string from a Vlan object
        """
        vlan_interface = f"{configuration.interface}.{configuration.vlan_tag}"
        config_string = f"{configuration.if_control} {vlan_interface}\n"

        for address_config in configuration.addresses:
            address_config_string = f"iface {vlan_interface} {address_config.family} {address_config.address_type}\n"
            # pp([*address_config.model_fields.keys(), *address_config.model_extra.keys()])
            for key in [
                *address_config.model_fields.keys(),
                *address_config.model_extra.keys(),
            ]:
                # Skip null keys, as well as keys that are used for the data but not actually valid interface config
                if (
                    key in ["family", "address_type"]
                    or getattr(address_config, key) is None
                ):
                    continue
                # print(key)
                address_config_string += f"\t{address_config.model_fields[key].serialization_alias or key} {getattr(address_config, key)}\n"
            config_string += address_config_string
            # TODO: Possibly validate details in here.
        return config_string

    @staticmethod
    async def check_interface_exists(interface: str) -> bool:
        ethernet_interfaces = (
            await run_cli_async("ls /sys/class/net/ | grep eth")
        ).split("\n")
        ethernet_interfaces = set([i.split(".")[0] for i in ethernet_interfaces if i])
        return interface in ethernet_interfaces

    async def create_update_vlan(
        self, configuration: Vlan, require_existing_interface: bool = True
    ):
        """
        Creates or updates a VLAN definition for a given interface.
        """

        # Validate that the requested interface exists
        if require_existing_interface and not await self.check_interface_exists(
            configuration.interface
        ):
            # return {
            #     'success': False,
            #     'result': self.vlans,
            #     'errors': {f"Interface {configuration.interface} does not exist"}
            # }
            raise ValidationError(
                f"Interface {configuration.interface} does not exist", status_code=400
            )

        # If there's not already a vlan-raw-device set, set it for each address
        for address in configuration.addresses:
            if address.vlan_raw_device is None:
                address.vlan_raw_device = configuration.interface
                # address['vlan-raw-device'] = configuration.interface

        # Dump the given VLAN configuration to a basic dict to match the output of get_vlans
        config_obj = configuration.model_dump(
            by_alias=True, exclude_unset=True, exclude_none=True
        )

        # Scan existing to find a matching interface:
        replaced = False
        for vlan_index, existing_vlan in enumerate(self.vlans):
            # If the right interface
            if existing_vlan["interface"] == configuration.interface and str(
                existing_vlan["vlan_tag"]
            ) == str(configuration.vlan_tag):
                # No sophisticated replace logic, just dumb swap for now.
                self.vlans[vlan_index] = config_obj
                replaced = True
        if not replaced:
            self.vlans.append(config_obj)

        self.persist_vlans()
        return {"success": True, "result": self.vlans, "errors": {}}

    async def remove_vlan(
        self, interface: str, vlan_tag: Union[str, int], allow_missing=False
    ):
        """
        Removes a VLAN definition for a given interface.
        """

        # Scan existing to find a matching interface:
        original_length = len(self.vlans)

        self.vlans = [
            i
            for i in self.vlans
            if not (i["interface"] == interface and str(i["vlan_tag"]) == str(vlan_tag))
        ]

        if original_length == len(self.vlans):
            # TODO: is this really a validation error?
            raise ValidationError(
                f"Interface {interface} with VLAN {vlan_tag} does not exist",
                status_code=400,
            )

        self.persist_vlans()
        return {"success": True, "result": self.vlans, "errors": {}}

    def persist_vlans(self):
        output_string = "\n".join(
            map(
                lambda f: self.generate_if_config_from_object(Vlan.model_validate(f)),
                self.vlans,
            )
        )

        with open(self.vlan_interface_file, "w") as interface_file:
            interface_file.write(output_string)
