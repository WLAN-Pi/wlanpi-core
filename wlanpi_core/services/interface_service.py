from collections import namedtuple
from typing import List

from .helpers import flag_last_object, run_cli_async

# from wlanpi_core.models.validation_error import ValidationError


PHYMapping = namedtuple("PHYMapping", "phy_id interface")
ChannelMapping = namedtuple("ChannelMapping", "center_channel_frequency channel_widths")


async def set_monitor_mode(interface: str) -> List:
    """
    wpa_cli -i wlan0 terminate
    ip link set wlan0 down
    iw dev wlan0 set monitor none
    iw dev wlan0 set type monitor
    ip link set wlan1 up
    """
    # TODO: Add set_monitor_mode() implementation
    return []


def sanitize_line(line: str) -> str:
    """
    Sanitize line
    """
    return line.strip().lower()


def parse_iw_dev(iw_dev_output: str) -> List:
    """
    Parse iw dev output
    """
    mappings = []
    phy = ""
    interface = ""
    for line in iw_dev_output.splitlines():
        line = sanitize_line(line)
        if line.startswith("phy"):
            phy = line.replace("#", "")
        if line.startswith("interface"):
            interface = line.split(" ")[1]
            mappings.append(PHYMapping(phy, interface))
    return mappings


async def get_phy_interface_mapping() -> List:
    """
    Run `iw dev` and return a list of phys mapped to interface names
    """

    return parse_iw_dev(await run_cli_async(f"iw dev"))


async def get_center_channel_frequencies(phy_id: str) -> List[ChannelMapping]:
    """
    Parse iw phy phy# channels to return channel mapping
    """
    channels_output = await run_cli_async(f"iw phy {phy_id} channels")
    frequencies = []
    first = True
    channel_center_frequency = 0
    channel_mapping = []
    for line, is_last_line in flag_last_object(channels_output.splitlines()):
        line = sanitize_line(line)
        if "*" in line and "mhz" in line:
            if "disabled" not in line:
                if first:
                    first = False
                    channel_center_frequency = line.split(" ")[1]
                    continue
                else:
                    frequencies.append(
                        ChannelMapping(channel_center_frequency, channel_mapping)
                    )
                    channel_center_frequency = line.split(" ")[1]
            continue
        if "channel widths" in line:
            line = line.replace("channel widths:", "").strip()
            channel_mapping = (
                line.replace("20mhz", "ht20")
                .upper()
                .replace("VHT80", "80MHz")
                .replace("VHT160", "160MHz")
                .split(" ")
            )
        if is_last_line:
            frequencies.append(
                ChannelMapping(channel_center_frequency, channel_mapping)
            )
    return frequencies


async def get_wiphys():
    """
    Return list of wiphys
    """
    wiphys = {}
    phys = []

    phy_ids = await get_phy_interface_mapping()
    for mapping in phy_ids:
        phy = mapping.phy_id
        interface = mapping.interface
        channel_mappings = await get_center_channel_frequencies(phy)
        frequencies = []
        for channel_mapping in channel_mappings:
            frequencies.append(
                {
                    "frequency": channel_mapping.center_channel_frequency,
                    "widths": channel_mapping.channel_widths,
                }
            )
        wiphy = {"phy": phy, "interface": interface, "frequencies": frequencies}
        phys.append(wiphy)

    wiphys["wiphys"] = phys
    return wiphys
