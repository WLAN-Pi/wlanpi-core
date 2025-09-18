import asyncio
import time
from datetime import datetime
from typing import Callable

import dbus
from dbus import Interface
from dbus.exceptions import DBusException

from wlanpi_core.constants import (
    WPAS_DBUS_BSS_INTERFACE,
    WPAS_DBUS_INTERFACE,
    WPAS_DBUS_INTERFACES_INTERFACE,
    WPAS_DBUS_OPATH,
    WPAS_DBUS_SERVICE,
)
from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.network import get_interface_addresses

log = get_logger(__name__)


class AsyncDBusManager:
    """
    An asyncio-friendly wrapper for DBus operations without PyGObject dependency
    Uses polling instead of signals for state changes
    """

    def __init__(self):
        self.bus = dbus.SystemBus()

    async def poll_until_condition(
        self,
        condition_func: Callable[[], bool],
        timeout: int = 20,
        initial_interval: float = 0.1,
        max_interval: float = 0.5,
    ) -> bool:
        """
        Poll at regular intervals until condition_func returns True or timeout is reached
        Uses adaptive polling to reduce CPU usage

        Args:
            condition_func: Function that returns True when condition is met
            timeout: Maximum seconds to wait before giving up
            initial_interval: Starting polling interval in seconds
            max_interval: Maximum polling interval in seconds

        Returns:
            bool: True if condition was met, False if timed out
        """
        start_time = asyncio.get_event_loop().time()
        interval = initial_interval
        polls = 0

        while True:
            try:
                if condition_func():
                    return True
            except Exception as e:
                log.error(f"Error in condition function: {e}")

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                return False

            await asyncio.sleep(interval)
            polls += 1

            if polls > 10:
                interval = min(interval * 1.2, max_interval)

    def get_object_property(
        self,
        service_name: str,
        object_path: str,
        interface_name: str,
        property_name: str,
    ):
        """
        Get a property from a DBus object without using signals

        Args:
            service_name: DBus service name
            object_path: DBus object path
            interface_name: Interface name
            property_name: Property name

        Returns:
            The property value
        """
        obj = self.bus.get_object(service_name, object_path)
        return obj.Get(
            interface_name, property_name, dbus_interface=dbus.PROPERTIES_IFACE
        )

    def call_method(
        self,
        service_name: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        *args,
    ):
        """
        Call a method on a DBus object

        Args:
            service_name: DBus service name
            object_path: DBus object path
            interface_name: Interface name
            method_name: Method name
            *args: Method arguments

        Returns:
            Method return value
        """
        obj = self.bus.get_object(service_name, object_path)
        method = obj.get_dbus_method(method_name, interface_name)
        return method(*args)


# For running locally (not in API)
# import asyncio

DBUS_MANAGER = AsyncDBusManager()
BUS = dbus.SystemBus()

API_TIMEOUT = 20

# Define a global debug level variable
DEBUG_LEVEL = 1
# Debug Level 0: No messages are printed.
# Debug Level 1: Only low-level messages (level 1) are printed.
# Debug Level 2: Low-level and medium-level messages (levels 1 and 2) are printed.
# Debug Level 3: All messages (levels 1, 2, and 3) are printed.


def set_debug_level(level):
    """
    Sets the global debug level.

    :param level: The desired debug level (0 for no debug, higher values for more verbosity).
    """
    global DEBUG_LEVEL
    DEBUG_LEVEL = level


def debug_print(message, level):
    """
    Prints a message to the console based on the global debug level.

    :param message: The message to be printed.
    :param level: The level of the message (e.g., 1 for low, 2 for medium, 3 for high).
    """
    if level <= DEBUG_LEVEL:
        print(message)


allowed_scan_types = [
    "active",
    "passive",
]


def is_allowed_scan_type(scan: str):
    for allowed_scan_type in allowed_scan_types:
        if scan == allowed_scan_type:
            return True
    return False


def is_allowed_interface(interface: str, wpas_obj):
    available_interfaces = fetch_interfaces(wpas_obj)
    for allowed_interface in available_interfaces:
        if interface == allowed_interface:
            return True
    return False


def byte_array_to_string(s):
    r = ""
    for c in s:
        if c >= 32 and c < 127:
            r += "%c" % c
        else:
            r += " "
            # r += urllib.quote(chr(c))
    return r


def renew_dhcp(interface):
    """
    Uses dhclient to release and request a new DHCP lease
    """
    try:
        # Release the current DHCP lease
        run_command(["sudo", "dhclient", "-r", interface], raise_on_fail=True)
        time.sleep(3)
        # Obtain a new DHCP lease
        run_command(["sudo", "dhclient", interface], raise_on_fail=True)
    except RunCommandError as err:
        debug_print(
            f"Failed to renew DHCP. Code:{err.return_code}, Error: {err.error_msg}", 1
        )


def get_ip_address(interface):
    """
    Extract the IP Address from the linux ip add show <if> command
    """
    try:
        res = get_interface_addresses(interface)[interface]["inet"]
        if len(res):
            return res[0]
        return None
    except RunCommandError as err:
        debug_print(
            f"Failed to get IP address. Code:{err.return_code}, Error: {err.error_msg}",
            1,
        )


def getBss(bss):
    """
    Queries DBUS_BSS_INTERFACE through dbus for a BSS Path

    Example path: /fi/w1/wpa_supplicant1/Interfaces/0/BSSs/567
    """

    try:
        net_obj = bus.get_object(WPAS_DBUS_SERVICE, bss)
        # dbus.Interface(net_obj, WPAS_DBUS_BSS_INTERFACE)
        # Convert the byte-array to printable strings

        # Get the BSSID from the byte array
        val = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "BSSID", dbus_interface=dbus.PROPERTIES_IFACE
        )
        bssid = ""
        for item in val:
            bssid = bssid + ":%02x" % item
        bssid = bssid[1:]

        # Get the SSID from the byte array
        val = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "SSID", dbus_interface=dbus.PROPERTIES_IFACE
        )
        ssid = byte_array_to_string(val)

        # Get the WPA Type from the byte array
        val = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "WPA", dbus_interface=dbus.PROPERTIES_IFACE
        )
        if len(val["KeyMgmt"]) > 0:
            pass

        # Get the RSN Info from the byte array
        val = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "RSN", dbus_interface=dbus.PROPERTIES_IFACE
        )
        key_mgmt = "/".join([str(r) for r in val["KeyMgmt"]])

        # Get the Frequency from the byte array
        freq = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "Frequency", dbus_interface=dbus.PROPERTIES_IFACE
        )

        # Get the RSSI from the byte array
        signal = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "Signal", dbus_interface=dbus.PROPERTIES_IFACE
        )

        # Get the Phy Rates from the byte array
        rates = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "Rates", dbus_interface=dbus.PROPERTIES_IFACE
        )

        minrate = 0
        if len(rates) > 0:
            minrate = rates[-1]

        # Get the IEs from the byte array
        IEs = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "IEs", dbus_interface=dbus.PROPERTIES_IFACE
        )
        debug_print(f"IEs: {IEs}", 3)

        return {
            "ssid": ssid,
            "bssid": bssid,
            "key_mgmt": key_mgmt,
            "signal": signal,
            "freq": freq,
            "minrate": minrate,
        }

    except DBusException:
        return None
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)


def pretty_print_BSS(BSSPath):
    BSSDetails = getBss(BSSPath)
    if BSSDetails:
        ssid = BSSDetails["ssid"] if BSSDetails["ssid"] else "<hidden>"
        bssid = BSSDetails["bssid"]
        freq = BSSDetails["freq"]
        rssi = BSSDetails["signal"]
        key_mgmt = BSSDetails["key_mgmt"]
        minrate = BSSDetails["minrate"]

        result = f"[{bssid}] {freq}, {rssi}dBm, {minrate} | {ssid} [{key_mgmt}] "
        return result
    else:
        return f"BSS Path {BSSPath} could not be resolved"


def fetch_interfaces(wpas_obj):
    available_interfaces = []
    ifaces = wpas_obj.Get(
        WPAS_DBUS_INTERFACE, "Interfaces", dbus_interface=dbus.PROPERTIES_IFACE
    )
    debug_print("InterfacesRequested: %s" % (ifaces), 2)
    # time.sleep(3)
    for path in ifaces:
        debug_print("Resolving Interface Path: %s" % (path), 2)
        if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
        ifname = if_obj.Get(
            WPAS_DBUS_INTERFACES_INTERFACE,
            "Ifname",
            dbus_interface=dbus.PROPERTIES_IFACE,
        )
        available_interfaces.append({"interface": ifname})
        debug_print(f"Found interface : {ifname}", 2)
    return available_interfaces


def fetch_currentBSS(interface):
    # Refresh the path to the adapter and read back the current BSSID
    bssid = ""

    try:
        path = wpas.GetInterface(interface)
    except dbus.DBusException as exc:
        if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceUnknown:"):
            raise ValidationError(f"Interface unknown : {exc}", status_code=400)
        try:
            path = wpas.CreateInterface({"Ifname": interface, "Driver": "test"})
            time.sleep(1)
        except dbus.DBusException as exc:
            if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceExists:"):
                raise ValidationError(
                    f"Interface cannot be created : {exc}", status_code=400
                )

    time.sleep(1)

    if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
    # time.sleep(2)
    currentBssPath = if_obj.Get(
        WPAS_DBUS_INTERFACES_INTERFACE,
        "CurrentBSS",
        dbus_interface=dbus.PROPERTIES_IFACE,
    )
    debug_print("Checking BSS", 2)
    if currentBssPath != "/":
        currentBssPath.split("/")[-1]
        bssid = getBss(currentBssPath)
    debug_print(currentBssPath, 2)
    return bssid


"""
Call back functions
"""


def scanDone(success):
    debug_print(f"Scan done: success={success}", 1)
    global scan
    local_scan = []
    res = if_obj.Get(
        WPAS_DBUS_INTERFACES_INTERFACE, "BSSs", dbus_interface=dbus.PROPERTIES_IFACE
    )
    debug_print("Scanned wireless networks:", 1)
    for opath in res:
        bss = getBss(opath)
        if bss:
            local_scan.append(bss)
    scan = local_scan
    scancount = len(scan)
    debug_print(f"A Scan has completed with {scancount} results", 1)
    debug_print(scan, 3)


def networkSelected(network):
    # returns the current selected network path
    debug_print(f"Network Selected (Signal) : {network}", 1)
    selectedNetworkSSID.append(network)


def propertiesChanged(properties):
    debug_print(f"PropertiesChanged: {properties}", 2)
    if properties.get("State") is not None:
        state = properties["State"]

        if state == "completed":
            time.sleep(2)
            if currentInterface:
                renew_dhcp(currentInterface)
                ipaddr = get_ip_address(currentInterface)
                connectionEvents.append(
                    network.NetworkEvent(
                        event=f"IP Address {ipaddr} on {currentInterface}",
                        time=f"{datetime.now()}",
                    )
                )
            supplicantState.append(state)
            debug_print(f"Connection Completed: State: {state}", 1)
            # elif state == "scanning":
            debug_print("SCAN---", 3)
        elif state == "associating":
            debug_print(f"PropertiesChanged: {state}", 1)
        elif state == "authenticating":
            # scanning = properties["Scanning"]
            debug_print(f"PropertiesChanged: {state}", 1)
        elif state == "4way_handshake":
            debug_print(f"PropertiesChanged: {state}", 1)
            if properties.get("CurrentBSS"):
                bssidpath = properties["CurrentBSS"]
                debug_print(f"Handshake attempt to: {pretty_print_BSS(bssidpath)}", 1)
        else:
            debug_print(f"PropertiesChanged: State: {state}", 1)
        connectionEvents.append(
            network.NetworkEvent(event=f"{state}", time=f"{datetime.now()}")
        )
    elif properties.get("DisconnectReason") is not None:
        disconnectReason = properties["DisconnectReason"]
        debug_print(f"Disconnect Reason: {disconnectReason}", 1)
        if disconnectReason != 0:
            if disconnectReason == 3 or disconnectReason == -3:
                connectionEvents.append(
                    network.NetworkEvent(
                        event="Station is Leaving", time=f"{datetime.now()}"
                    )
                )
            elif disconnectReason == 15:
                connectionEvents.append(
                    network.NetworkEvent(
                        event="4-Way Handshake Fail (check password)",
                        time=f"{datetime.now()}",
                    )
                )
                supplicantState.append("authentication error")
            else:
                connectionEvents.append(
                    network.NetworkEvent(
                        event=f"Error: Disconnected [{disconnectReason}]",
                        time=f"{datetime.now()}",
                    )
                )
                supplicantState.append("disconnected")

    # For debugging purposes only
    # if properties.get("BSSs") is not None:
    #     print("Supplicant has found the following BSSs")
    #     for BSS in properties["BSSs"]:
    #         if len(BSS) > 0:
    #             print(pretty_print_BSS(BSS))

    if properties.get("CurrentAuthMode") is not None:
        currentAuthMode = properties["CurrentAuthMode"]
        debug_print(f"Current Auth Mode is {currentAuthMode}", 1)

    if properties.get("AuthStatusCode") is not None:
        authStatus = properties["AuthStatusCode"]
        debug_print(f"Auth Status: {authStatus}", 1)
        if authStatus == 0:
            connectionEvents.append(
                network.NetworkEvent(event="authenticated", time=f"{datetime.now()}")
            )
        else:
            connectionEvents.append(
                network.NetworkEvent(
                    event=f"authentication failed with code {authStatus}",
                    time=f"{datetime.now()}",
                )
            )
            supplicantState.append(f"authentication fail {authStatus}")


def setup_DBus_Supplicant_Access(interface):
    global bus
    global if_obj
    global iface
    global wpas
    global currentInterface

    bus = dbus.SystemBus()
    proxy = bus.get_object(WPAS_DBUS_SERVICE, WPAS_DBUS_OPATH)
    wpas = Interface(proxy, WPAS_DBUS_INTERFACE)

    try:
        path = wpas.GetInterface(interface)
        currentInterface = interface
    except dbus.DBusException as exc:
        if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceUnknown:"):
            raise ValidationError(f"Interface unknown : {exc}", status_code=400)
        try:
            path = wpas.CreateInterface({"Ifname": interface, "Driver": "test"})
            time.sleep(1)
        except dbus.DBusException as exc:
            if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceExists:"):
                raise ValidationError(
                    f"Interface cannot be created : {exc}", status_code=400
                )
    time.sleep(1)
    debug_print(path, 3)
    if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
    # time.sleep(1)
    iface = dbus.Interface(if_obj, WPAS_DBUS_INTERFACES_INTERFACE)


"""
These are the functions used to deliver the API
"""


async def get_systemd_network_interfaces(timeout: network.APIConfig):
    """
    Queries systemd via dbus to get a list of the available interfaces.
    """
    global bus
    bus = dbus.SystemBus()
    wpas_obj = bus.get_object(WPAS_DBUS_SERVICE, WPAS_DBUS_OPATH)
    debug_print("Checking available interfaces", 3)
    available_interfaces = fetch_interfaces(wpas_obj)
    debug_print(f"Available interfaces: {available_interfaces}", 3)
    return {"interfaces": available_interfaces}


async def get_async_systemd_network_scan(
    type: str, interface: network.Interface, timeout: network.APIConfig
):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """

    type = type.strip().lower()
    if is_allowed_scan_type(type):
        try:
            setup_DBus_Supplicant_Access(interface)

            global scan
            scan = []
            scanConfig = dbus.Dictionary({"Type": type}, signature="sv")

            iface.Scan(scanConfig)

            scan_successful = await DBUS_MANAGER.poll_until_condition(
                lambda: collect_scan_results(), timeout=timeout
            )

            if not scan_successful:
                return {"nets": []}

            # scan = [{"ssid": "A Network", "bssid": "11:22:33:44:55", "wpa": "no", "wpa2": "yes", "signal": -65, "freq": 5650}]
            return {"nets": scan}
        except DBusException as de:
            debug_print(f"DBUS Error State: {de}", 0)
        except ValueError as error:
            raise ValidationError(f"{error}", status_code=400)
    raise ValidationError(f"{type} is not a valid scan type", status_code=400)


def collect_scan_results():
    """
    Poll for scan results and collect them
    Returns True when scan results are found
    """
    global scan

    try:
        bss_list = if_obj.Get(
            WPAS_DBUS_INTERFACES_INTERFACE, "BSSs", dbus_interface=dbus.PROPERTIES_IFACE
        )

        if not bss_list or len(bss_list) == 0:
            return False

        local_scan = []
        for opath in bss_list:
            bss = getBss(opath)
            if bss:
                local_scan.append(bss)

        if len(local_scan) > 0:
            scan = local_scan
            return True
    except Exception as e:
        log.error(f"Error collecting scan results: {e}")

    return False


async def set_systemd_network_addNetwork(
    interface: network.Interface,
    netConfig: network.NetConfig,
    removeAllFirst: bool,
    timeout: network.APIConfig,
):
    """
    Uses wpa_supplicant to connect to a WLAN network.
    """
    global selectedNetworkSSID
    selectedNetworkSSID = []
    global supplicantState
    supplicantState = []
    global connectionEvents
    connectionEvents = []

    API_TIMEOUT = timeout

    debug_print("Setting up supplicant access", 3)
    setup_DBus_Supplicant_Access(interface)

    selectErr = None
    status = "uninitialised"
    bssid = {
        "ssid": "",
        "bssid": "",
        "key_mgmt": "",
        "signal": 0,
        "freq": 0,
        "minrate": 0,
    }
    response = network.NetworkSetupLog(selectErr="", eventLog=[])

    try:
        debug_print("Configuring DBUS", 3)

        # Remove all configured networks and apply the new network
        if removeAllFirst:
            debug_print("Removing existing connections", 2)
            netw = iface.RemoveAllNetworks()

        netConfig_cleaned = {k: v for k, v in netConfig if v is not None}
        netConfig_DBUS = dbus.Dictionary(netConfig_cleaned, signature="sv")
        netw = iface.AddNetwork(netConfig_DBUS)

        if netw != "/":
            debug_print("Valid network entry received", 2)
            # A valid network entry has been created - get the Index
            netw.split("/")[-1]

            # Select this network using its full path name
            selectErr = iface.SelectNetwork(netw)
            # time.sleep(10)
            debug_print(f"Network selected with result: {selectErr}", 2)

            if selectErr == None:
                # Poll for connection completion instead of waiting for signals
                connected = await monitor_connection_state(API_TIMEOUT)

                if connected:
                    # Check the current BSSID post connection
                    bssidPath = if_obj.Get(
                        WPAS_DBUS_INTERFACES_INTERFACE,
                        "CurrentBSS",
                        dbus_interface=dbus.PROPERTIES_IFACE,
                    )
                    if bssidPath != "/":
                        bssidresolution = getBss(bssidPath)
                        if bssidresolution:
                            bssid = bssidresolution
                            status = "connected"
                        else:
                            status = "connection_lost"
                    else:
                        status = "connection_lost"
                else:
                    status = "connection_timeout"
            else:
                status = "connection_error"
    except DBusException as de:
        debug_print(f"DBUS Error State: {de}", 0)
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)

    response.eventLog = connectionEvents
    if selectErr != None:
        response.selectErr = str(selectErr)
    else:
        response.selectErr = ""

    return {
        "status": status,
        "response": response,
        "connectedNet": bssid,
        "input": netConfig.ssid,
    }


async def monitor_connection_state(timeout):
    """
    Monitor connection state by polling
    """
    start_time = asyncio.get_event_loop().time()
    interval = 0.5

    while True:
        try:
            state = if_obj.Get(
                WPAS_DBUS_INTERFACES_INTERFACE,
                "State",
                dbus_interface=dbus.PROPERTIES_IFACE,
            )

            connectionEvents.append(
                network.NetworkEvent(event=f"{state}", time=f"{datetime.now()}")
            )

            if state == "completed":
                supplicantState.append(state)
                if currentInterface:
                    renew_dhcp(currentInterface)
                    ipaddr = get_ip_address(currentInterface)
                    connectionEvents.append(
                        network.NetworkEvent(
                            event=f"IP Address {ipaddr} on {currentInterface}",
                            time=f"{datetime.now()}",
                        )
                    )
                return True

            elif state in ["disconnected", "inactive"]:
                supplicantState.append("fail")
                return False

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                return False

            await asyncio.sleep(interval)

        except Exception as e:
            log.error(f"Error monitoring connection state: {e}")
            await asyncio.sleep(interval)


async def get_systemd_network_currentNetwork_details(
    interface: network.Interface, timeout: network.APIConfig
):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """
    try:
        res = ""
        setup_DBus_Supplicant_Access(interface)
        await asyncio.sleep(1)

        # res = fetch_currentBSS(interface)
        bssidPath = if_obj.Get(
            WPAS_DBUS_INTERFACES_INTERFACE,
            "CurrentBSS",
            dbus_interface=dbus.PROPERTIES_IFACE,
        )

        if bssidPath != "/":
            res = getBss(bssidPath)
            return {"connectedStatus": True, "connectedNet": res}
        else:
            return {"connectedStatus": False, "connectedNet": None}
    except DBusException:
        debug_print("DBUS Error State: {de}", 0)
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)


# async def main():
#     await get_async_systemd_network_scan('passive', 'wlan0')
#     # testnet = '{"ssid":"PiAP_6","psk":"wlanpieea","key_mgmt":"SAE","ieee80211w":2}'
#     # await set_systemd_network_addNetwork('wlan0',testnet,True)

# if __name__ == "__main__":
# 	asyncio.run(main())

# ### -- Test for printing out the connected network ###
# if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
# res = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'CurrentNetwork', dbus_interface=dbus.PROPERTIES_IFACE)
# # showNetwork(res)

# ### -- Test for printing out the connected network ###
# if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
# res = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'CurrentBSS', dbus_interface=dbus.PROPERTIES_IFACE)
# print(getBss(res))

if __name__ == "__main__":
    print(get_ip_address("eth0"))
