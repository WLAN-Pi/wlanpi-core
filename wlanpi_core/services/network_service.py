import logging
from enum import Enum
from typing import Optional, Union

from wlanpi_core.models.network.wlan.exceptions import (
    WlanDBUSException,
    WlanDBUSInterfaceCreationError,
)
from wlanpi_core.models.network.wlan.wlan_dbus import WlanDBUS
from wlanpi_core.models.network.wlan.wlan_dbus_interface import WlanDBUSInterface
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.schemas.network.network import SupplicantNetwork
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.network import get_interface_details, list_wlan_interfaces

"""
These are the functions used to deliver the API
"""


async def get_systemd_network_interfaces(timeout: int):
    """
    Queries systemd via dbus to get a list of the available interfaces.
    """
    try:
        wlan_dbus = WlanDBUS()
        available_interfaces = wlan_dbus.get_systemd_network_interfaces(timeout=timeout)
        logging.info(f"Available interfaces: {available_interfaces}")
        return {"interfaces": available_interfaces}
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except WlanDBUSException as err:
        # Need to Split exceptions into validation and actual failures
        raise ValidationError(str(err), status_code=400) from err


async def get_wireless_network_scan_async(
    scan_type: Enum(*WlanDBUSInterface.ALLOWED_SCAN_TYPES), interface: str, timeout: int
):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """
    try:
        wlan_dbus = WlanDBUS()
        clean_scan_type = scan_type.strip().lower() if scan_type else None
        if not clean_scan_type or (
            clean_scan_type not in WlanDBUSInterface.ALLOWED_SCAN_TYPES
        ):
            raise ValidationError(
                f"scan type must be one of: {', '.join(WlanDBUSInterface.ALLOWED_SCAN_TYPES)}",
                status_code=400,
            )

        interface_obj = wlan_dbus.get_interface(interface)
        return {
            "nets": await interface_obj.get_network_scan(scan_type, timeout=timeout)
        }
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except (WlanDBUSException, ValueError) as err:
        # Need to Split exceptions into validation and actual failures
        raise ValidationError(str(err), status_code=400) from err


async def add_wireless_network(
    interface: str,
    net_config: network.WlanConfig,
    remove_all_first: bool,
    timeout: Optional[int],
):
    """
    Uses wpa_supplicant to connect to a WLAN network.
    """
    try:
        wlan_dbus = WlanDBUS()
        return await wlan_dbus.get_interface(interface).add_network(
            wlan_config=net_config, remove_others=remove_all_first, timeout=timeout
        )
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)


async def get_current_wireless_network_details(interface: str, timeout: int):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """
    try:
        wlan_dbus = WlanDBUS()
        return wlan_dbus.get_interface(interface).get_current_network_details()
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except WlanDBUSException as err:
        raise ValidationError(str(err), status_code=400) from err


async def disconnect_wireless_network(
    interface: str,
    timeout: Optional[int],
):
    """
    Uses wpa_supplicant to disconnect to a WLAN network.
    """
    try:
        wlan_dbus = WlanDBUS()
        return wlan_dbus.get_interface(interface).disconnect()
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)


async def remove_all_networks(
    interface: str,
):
    """
    Uses wpa_supplicant to connect to a WLAN network.
    """
    try:
        wlan_dbus = WlanDBUS()
        return wlan_dbus.get_interface(interface).remove_all_networks()
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)


async def remove_network(
    interface: str,
    network_id: int,
):
    """
    Uses wpa_supplicant to remove a network from the list of known networks.
    """
    try:
        wlan_dbus = WlanDBUS()
        return wlan_dbus.get_interface(interface).remove_network(network_id)
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)


async def get_network(
    interface: str,
    network_id: int,
) -> SupplicantNetwork:
    """
    Uses wpa_supplicant to remove a network from the list of known networks.
    """
    try:
        wlan_dbus = WlanDBUS()
        return wlan_dbus.get_interface(interface).get_network(network_id)
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)


async def networks(
    interface: str,
) -> dict[int, SupplicantNetwork]:
    """
    Uses wpa_supplicant to connect to a WLAN network.
    """
    try:
        wlan_dbus = WlanDBUS()
        return wlan_dbus.get_interface(interface).networks()
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)


async def current_network(
    interface: str,
) -> Optional[SupplicantNetwork]:
    """
    Uses wpa_supplicant to connect to a WLAN network.
    """
    try:
        wlan_dbus = WlanDBUS()
        return wlan_dbus.get_interface(interface).current_network()
    except WlanDBUSInterfaceCreationError as error:
        raise ValidationError(
            "Could not create interface. Check that the requested interface exists.\n"
            f"Original error: {str(error)}",
            status_code=400,
        )
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)


async def interface_details(
    interface: Optional[str],
) -> Optional[dict[str, dict[str, any]]]:
    return get_interface_details(interface)


def get_iw_link(interface: str) -> dict[str, Union[bool, str, int, float, None]]:
    if interface not in list_wlan_interfaces():
        raise ValidationError(
            f"{interface} is not a wireless interface", status_code=400
        )
    lines = run_command(["iw", "dev", interface, "link"]).stdout.split("\n")
    state = lines[0].strip()
    data: dict[str, Union[bool, str, int, float, None]] = {
        "connected": state != "Not connected.",
        "ssid": None,  # SSID # Kronos-5
        "bssid": None,  # from state line
        "freq": None,  # freq # 5220.0
        # "rx": None,  # RX # 402298 bytes (2063 packets)
        "rx_bytes": None,
        "rx_packets": None,
        # "tx": None,  # TX # 19503 bytes (137 packets)
        "tx_bytes": None,
        "tx_packets": None,
        # "signal": None,  # signal # -70 dBm
        "signal_dbm": None,
        "rx_bitrate": None,  # rx bitrate # 54.0 MBit/s VHT-MCS 1 40MHz VHT-NSS 2
        "tx_bitrate": None,  # tx bitrate # 351.0 MBit/s VHT-MCS 4 80MHz VHT-NSS 2
        "bss_flags": None,  # bss flags # short-slot-time
        "dtim_period": None,  # dtim period # 3
        "beacon_int": None,  # beacon int # 100
    }

    if not data["connected"]:
        return data

    # Populate the lines as much as possible
    data["bssid"] = lines[0].strip().split(" ")[2]
    for line in [x for x in lines[1:] if x != ""]:
        key, val = line.split(":", 1)
        data[key.strip().lower().replace(" ", "_")] = val.strip()

    # Rebuild him better, faster, stronger
    data["freq"] = float(data["freq"])
    data["signal_dbm"] = int(data["signal"].split()[0])
    del data["signal"]

    rx_split = data["rx"].split()
    data["rx_bytes"] = int(rx_split[0])
    data["rx_packets"] = int(rx_split[2][1:])
    del data["rx"]

    tx_split = data["tx"].split()
    data["tx_bytes"] = int(tx_split[0])
    data["tx_packets"] = int(tx_split[2][1:])
    del data["tx"]

    data["dtim_period"] = int(data["dtim_period"])
    data["beacon_int"] = int(data["beacon_int"])

    return data
