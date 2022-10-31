from collections import namedtuple
from typing import List

from .helpers import flag_last_object, run_cli_async, __20MHZ_FREQUENCY_CHANNEL_MAP

# from wlanpi_core.models.validation_error import ValidationError


PHYMapping = namedtuple("PHYMapping", "phy_id interface")
ChannelMapping = namedtuple("ChannelMapping", "channel_number center_channel_frequency channel_widths")


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


def parse_iw_dev_for_mappings(iw_dev_output: str) -> List:
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

    return parse_iw_dev_for_mappings(await run_cli_async(f"iw dev"))


def get_center_channel_frequencies(channels_output: str) -> List[ChannelMapping]:
    """
    Parse iw phy phy# channels to return channel mapping

    Disabled channels are not returned
    """
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
                        ChannelMapping(__20MHZ_FREQUENCY_CHANNEL_MAP.get(int(channel_center_frequency), 0), channel_center_frequency, channel_mapping)
                    )
                    channel_center_frequency = line.split(" ")[1]
            continue
        if "channel widths" in line:
            line = line.replace("channel widths:", "").strip()
            channel_mapping = (
                line.upper()
                .replace("20MHZ", "20")
                .replace("HT40-", "40-")
                .replace("HT40+", "40+")
                .replace("VHT80", "80")
                .replace("VHT160", "160")
                .split(" ")
            )
        if is_last_line:
            frequencies.append(
                ChannelMapping(__20MHZ_FREQUENCY_CHANNEL_MAP.get(int(channel_center_frequency), 0), channel_center_frequency, channel_mapping)
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
        channels_output = await run_cli_async(f"iw phy {phy} channels")
        channel_mappings = get_center_channel_frequencies(channels_output)
        frequencies = []
        for channel_mapping in channel_mappings:
            frequencies.append(
                {
                    "channel": channel_mapping.channel_number,
                    "freq": int(channel_mapping.center_channel_frequency),
                    "widths": channel_mapping.channel_widths,
                }
            )
        operstate = await run_cli_async(f"cat /sys/class/net/{interface}/operstate")
        operstate = operstate.strip().lower()
        mac = await run_cli_async(f"cat /sys/class/net/{interface}/address")
        mac = mac.strip().lower()
        driver = await run_cli_async(f"readlink -f /sys/class/net/{interface}/device/driver")
        driver = driver.split("/")[-1].strip().lower()
        interface_type = await run_cli_async(f"cat /sys/class/net/{interface}/type")
        mode = "unknown"
        try:
            _type = int(interface_type)
            if _type == 1:
                mode = "managed"
            elif _type == 801:
                mode = "monitor"
            elif _type == 802:
                mode = "monitor"
            elif (
                _type == 803
            ):  # https://github.com/torvalds/linux/blob/master/include/uapi/linux/if_arp.h#L91
                mode = "monitor"
        except ValueError:
            pass
        wiphy = {"phy": phy, "interface": interface, "mac": mac, "driver": driver, "operstate": operstate, "mode": mode, "channels": frequencies}
        phys.append(wiphy)

    wiphys["wiphys"] = phys
    return wiphys
