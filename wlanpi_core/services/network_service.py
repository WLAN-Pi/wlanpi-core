import subprocess
import time
from datetime import datetime

import dbus
from dbus import Interface
from dbus.exceptions import DBusException
from gi.repository import GLib

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas import network
from wlanpi_core.services.helpers import debug_print

# For running locally (not in API)
# import asyncio

WPAS_DBUS_SERVICE = "fi.w1.wpa_supplicant1"
WPAS_DBUS_INTERFACE = "fi.w1.wpa_supplicant1"
WPAS_DBUS_OPATH = "/fi/w1/wpa_supplicant1"
WPAS_DBUS_INTERFACES_INTERFACE = "fi.w1.wpa_supplicant1.Interface"
WPAS_DBUS_INTERFACES_OPATH = "/fi/w1/wpa_supplicant1/Interfaces"
WPAS_DBUS_BSS_INTERFACE = "fi.w1.wpa_supplicant1.BSS"
WPAS_DBUS_NETWORK_INTERFACE = "fi.w1.wpa_supplicant1.Network"

API_TIMEOUT = 20


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
        subprocess.run(["sudo", "dhclient", "-r", interface], check=True)
        time.sleep(3)
        # Obtain a new DHCP lease
        subprocess.run(["sudo", "dhclient", interface], check=True)
    except subprocess.CalledProcessError as spe:
        debug_print(f"Failed to renew DHCP. Error {spe}", 1)


def get_ip_address(interface):
    """
    Extract the IP Address from the linux ip add show <if> command
    """
    try:
        # Run the command to get details for a specific interface
        result = subprocess.run(
            ["ip", "addr", "show", interface],
            capture_output=True,
            text=True,
            check=True,
        )

        # Process the output to find the inet line which contains the IPv4 address
        for line in result.stdout.split("\n"):
            if "inet " in line:
                # Extract the IP address from the line
                ip_address = line.strip().split(" ")[1].split("/")[0]
                return ip_address
    except subprocess.CalledProcessError as spe:
        debug_print("Failed to get IP address. Error {spe}", 1)
        return None


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
Call back functions from GLib
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
    API_TIMEOUT = timeout
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    type = type.strip().lower()
    if is_allowed_scan_type(type):

        try:
            setup_DBus_Supplicant_Access(interface)

            global scan
            scan = []
            scanConfig = dbus.Dictionary({"Type": type}, signature="sv")

            scan_handler = bus.add_signal_receiver(
                scanDone,
                dbus_interface=WPAS_DBUS_INTERFACES_INTERFACE,
                signal_name="ScanDone",
            )

            iface.Scan(scanConfig)

            main_context = GLib.MainContext.default()
            timeout_check = 0
            while scan == [] and timeout_check <= API_TIMEOUT:
                time.sleep(1)
                timeout_check += 1
                debug_print(
                    f"Scan request timeout state: {timeout_check} / {API_TIMEOUT}", 2
                )
                main_context.iteration(False)

            scan_handler.remove()

            # scan = [{"ssid": "A Network", "bssid": "11:22:33:44:55", "wpa": "no", "wpa2": "yes", "signal": -65, "freq": 5650}]
            return {"nets": scan}
        except DBusException as de:
            debug_print(f"DBUS Error State: {de}", 0)
        except ValueError as error:
            raise ValidationError(f"{error}", status_code=400)
    raise ValidationError(f"{type} is not a valid scan type", status_code=400)


async def set_systemd_network_addNetwork(
    interface: network.Interface,
    netConfig: network.WlanConfig,
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
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
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
        network_change_handler = bus.add_signal_receiver(
            networkSelected,
            dbus_interface=WPAS_DBUS_INTERFACES_INTERFACE,
            signal_name="NetworkSelected",
        )

        properties_change_handler = bus.add_signal_receiver(
            propertiesChanged,
            dbus_interface=WPAS_DBUS_INTERFACES_INTERFACE,
            signal_name="PropertiesChanged",
        )

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
                # The network selection has been successsfully applied (does not mean a network is selected)
                main_context = GLib.MainContext.default()
                timeout_check = 0
                while supplicantState == [] and timeout_check <= API_TIMEOUT:
                    time.sleep(1)
                    timeout_check += 1
                    debug_print(
                        f"Select request timeout: {timeout_check} / {API_TIMEOUT}", 2
                    )
                    main_context.iteration(False)

                if supplicantState != []:
                    if supplicantState[0] == "completed":
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
                                debug_print(f"Logged Events: {connectionEvents}", 2)
                                debug_print("Connected", 1)
                                status = "connected"
                            else:
                                debug_print(f"select error: {selectErr}", 2)
                                debug_print(f"Logged Events: {connectionEvents}", 2)
                                debug_print(
                                    "Connection failed. Post connection check returned no network",
                                    1,
                                )
                                status = "connection_lost"
                        else:
                            debug_print(f"select error: {selectErr}", 2)
                            debug_print(f"Logged Events: {connectionEvents}", 2)
                            debug_print("Connection failed. Aborting", 1)
                            status = "connection_lost"

                    elif supplicantState[0] == "fail":
                        debug_print(f"select error: {selectErr}", 2)
                        debug_print(f"Logged Events: {connectionEvents}", 2)
                        debug_print("Connection failed. Aborting", 1)
                        status = f"connection_failed:{supplicantState[0]}"
                    else:
                        debug_print(f"select error: {selectErr}", 2)
                        debug_print(f"Logged Events: {connectionEvents}", 2)
                        debug_print("Connection failed. Aborting", 1)
                        status = f"connection failed:{supplicantState[0]}"
                else:
                    debug_print(f"select error: {selectErr}", 2)
                    debug_print(f"Logged Events: {connectionEvents}", 2)
                    debug_print(f"No connection", 1)
                    status = "Network_not_found"

            else:
                debug_print(f"select error: {selectErr}", 2)
                debug_print(f"Logged Events: {connectionEvents}", 2)
                if timeout_check >= API_TIMEOUT:
                    status = "Connection Timeout"
                    debug_print("Connection Timeout", 1)
                else:
                    status = "Connection Err"
                    debug_print("Connection Err", 1)

    except DBusException as de:
        debug_print(f"DBUS Error State: {de}", 0)
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400)

    network_change_handler.remove()
    properties_change_handler.remove()

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


async def get_systemd_network_currentNetwork_details(
    interface: network.Interface, timeout: network.APIConfig
):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """
    try:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        res = ""
        setup_DBus_Supplicant_Access(interface)
        time.sleep(1)

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
