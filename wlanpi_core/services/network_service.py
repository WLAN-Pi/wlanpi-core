
import dbus
from dbus import Boolean, Interface, SystemBus, Dictionary
from dbus.exceptions import DBusException
import sys
import time
from datetime import datetime
import json
from wlanpi_core.models.validation_error import ValidationError
from gi.repository import GObject, GLib
from dbus.mainloop.glib import DBusGMainLoop

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
    import urllib
    r = ""    
    for c in s:
        if c >= 32 and c < 127:
            r += "%c" % c
        else:
            r += " "
            #r += urllib.quote(chr(c))
    return r

# def showNetwork(net):
#     net_obj = bus.get_object(WPAS_DBUS_SERVICE, net)
#     net = dbus.Interface(net_obj, WPAS_DBUS_NETWORK_INTERFACE)
#     enabled = net_obj.Get(WPAS_DBUS_NETWORK_INTERFACE, 'Enabled',
#               dbus_interface=dbus.PROPERTIES_IFACE)
#     network_properties = net_obj.Get(WPAS_DBUS_NETWORK_INTERFACE, 'Properties',
#               dbus_interface=dbus.PROPERTIES_IFACE)

#     print(network_properties)
#     print("Net %s BSSID: %s Protocol: %s Pairwise: %s Key: %s [Enabled: %s]" % (network_properties.get('ssid',''), network_properties.get('bssid',''), network_properties.get('proto',''), network_properties.get('pairwise',''), network_properties.get('key_mgmt',''), enabled))

def getBss(bss):
    net_obj = bus.get_object(WPAS_DBUS_SERVICE, bss)
    net = dbus.Interface(net_obj, WPAS_DBUS_BSS_INTERFACE)
    # Convert the byte-array for SSID and BSSID to printable strings
    val = net_obj.Get(WPAS_DBUS_BSS_INTERFACE, 'BSSID',
              dbus_interface=dbus.PROPERTIES_IFACE)
    bssid = ""
    for item in val:
        bssid = bssid + ":%02x" % item
    bssid = bssid[1:]
    val = net_obj.Get(WPAS_DBUS_BSS_INTERFACE, 'SSID',
              dbus_interface=dbus.PROPERTIES_IFACE)
    ssid = byte_array_to_string(val)
    val = net_obj.Get(WPAS_DBUS_BSS_INTERFACE, 'WPA',
              dbus_interface=dbus.PROPERTIES_IFACE)
    wpa = "no"
    if len(val["KeyMgmt"]) > 0:
        wpa = "yes"
    val = net_obj.Get(WPAS_DBUS_BSS_INTERFACE, 'RSN',
              dbus_interface=dbus.PROPERTIES_IFACE)
    wpa2 = "no"
    if len(val["KeyMgmt"]) > 0:
        wpa2 = "yes"
    rsn = val
    freq = net_obj.Get(WPAS_DBUS_BSS_INTERFACE, 'Frequency',
               dbus_interface=dbus.PROPERTIES_IFACE)
    signal = net_obj.Get(WPAS_DBUS_BSS_INTERFACE, 'Signal',
                 dbus_interface=dbus.PROPERTIES_IFACE)
    val = net_obj.Get(WPAS_DBUS_BSS_INTERFACE, 'Rates',
              dbus_interface=dbus.PROPERTIES_IFACE)
    IEs = net_obj.Get(WPAS_DBUS_BSS_INTERFACE, 'IEs',
              dbus_interface=dbus.PROPERTIES_IFACE)
    if len(val) > 0:
        maxrate = val[0] / 1000000
    else:
        maxrate = 0
    
    bssDict = {
        "ssid": ssid,
        "bssid": bssid,
        "wpa": wpa,
        "wpa2": wpa2,
        "signal": signal,
        "freq": freq
    }

    return bssDict

def fetch_interfaces(wpas_obj):
    available_interfaces = []
    ifaces = wpas_obj.Get(WPAS_DBUS_INTERFACE, 'Interfaces',
                  dbus_interface=dbus.PROPERTIES_IFACE)
    time.sleep(1)
    for path in ifaces:
        if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
        ifname = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'Ifname',
                  dbus_interface=dbus.PROPERTIES_IFACE)
        available_interfaces.append({'interface':ifname})
        # print("Found interface : ", ifname)
    return available_interfaces

def fetch_currentSSID():
    time.sleep(1)
    currentNet = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'CurrentNetwork', dbus_interface=dbus.PROPERTIES_IFACE)
    # print("Current Net Selected: ")
    # print(currentNet)
    return currentNet

def fetch_currentBSS(interface):
    # Refresh the path to the adapter and read back the current BSSID
    bssidPath = ""
    bssid = ""
    
    try:
        path = wpas.GetInterface(interface)
    except dbus.DBusException as exc:
        if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceUnknown:"):
            raise ValidationError(
                f"Interface unknown : {exc}", status_code=400
            )
        try:
            path = wpas.CreateInterface({'Ifname': interface, 'Driver': 'test'})
            time.sleep(1)
        except dbus.DBusException as exc:
            if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceExists:"):
                raise ValidationError(
                    f"Interface cannot be created : {exc}", status_code=400
                )
    time.sleep(2)
    if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
    time.sleep(2)
    currentBssPath = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'CurrentBSS', dbus_interface=dbus.PROPERTIES_IFACE)
    # print("Checking BSS")
    if currentBssPath != '/':
        bssidPath = currentBssPath.split("/")[-1]
        bssid = getBss(currentBssPath)
    # print(currentBssPath)
    return bssid


"""
Call back functions from GLib
"""
def scanDone(success):
    # print("Scan done: success=%s" % success)
    global scan
    local_scan = []
    res = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'BSSs',
             dbus_interface=dbus.PROPERTIES_IFACE)
    # print("Scanned wireless networks:")
    for opath in res:
        local_scan.append(getBss(opath))
    scan = local_scan
    # print(scan)

def networkSelected(network):
    # returns the current selected network path
    # print("Network Selected (Signal) : %s", network)
    selectedNetworkSSID.append(network)
    
def propertiesChanged(properties):
	print("PropertiesChanged: %s" % (properties))
	if properties.get("State") is not None:
		state = properties["State"]
		# print("PropertiesChanged: State: %s" % state)
		if state == 'completed':
			supplicantState.append(state)
		connectionEvents.append(f"{state} : {datetime.now()}")
	elif properties.get("AuthStatusCode") is not None:
		authStatus = properties["AuthStatusCode"]
		# print("Auth Status: %s" % authStatus)
		if authStatus == 0:
			connectionEvents.append(f"authenticated : {datetime.now()}")
		else:
			connectionEvents.append(f"authentication failed: {datetime.now()}")
			supplicantState.append(state)

def setup_DBus_Supplicant_Access(interface):
    global bus
    global if_obj
    global iface
    global wpas

    bus = dbus.SystemBus()
    proxy = bus.get_object(WPAS_DBUS_SERVICE,WPAS_DBUS_OPATH)
    wpas = Interface(proxy, WPAS_DBUS_INTERFACE)

    try:
        path = wpas.GetInterface(interface)
    except dbus.DBusException as exc:
        if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceUnknown:"):
            raise ValidationError(
                f"Interface unknown : {exc}", status_code=400
            )
        try:
            path = wpas.CreateInterface({'Ifname': interface, 'Driver': 'test'})
            time.sleep(1)
        except dbus.DBusException as exc:
            if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceExists:"):
                raise ValidationError(
                    f"Interface cannot be created : {exc}", status_code=400
                )
    time.sleep(1)
    # print(path)
    if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
    time.sleep(1)
    iface = dbus.Interface(if_obj, WPAS_DBUS_INTERFACES_INTERFACE)


"""
These are the functions used to deliver the API
"""
async def get_systemd_network_interfaces():
    """
    Queries systemd via dbus to get a list of the available interfaces.
    """
    global bus
    bus = dbus.SystemBus()
    wpas_obj = bus.get_object(WPAS_DBUS_SERVICE, WPAS_DBUS_OPATH)
    available_interfaces = fetch_interfaces(wpas_obj)
    
    return {"interfaces": available_interfaces}

async def get_async_systemd_network_scan(type: str, interface: str):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    type = type.strip().lower()
    if is_allowed_scan_type(type):

        setup_DBus_Supplicant_Access(interface)

        global scan
        scan = []
        scanConfig = dbus.Dictionary({'Type': type}, signature='sv')

        bus.add_signal_receiver(scanDone,
				dbus_interface=WPAS_DBUS_INTERFACES_INTERFACE,
				signal_name="ScanDone")
          
        iface.Scan(scanConfig)

        main_context = GLib.MainContext.default()
        timeout_check = 0
        while scan == [] and timeout_check <= API_TIMEOUT:
            time.sleep(1)
            timeout_check += 1
            # print (timeout_check)
            main_context.iteration(False)   
        
        # scan = [{"ssid": "A Network", "bssid": "11:22:33:44:55", "wpa": "no", "wpa2": "yes", "signal": -65, "freq": 5650}]
        return {"nets": scan}

    raise ValidationError(
        f"{type} is not a valid scan type", status_code=400
    )

async def set_systemd_network_addNetwork(interface: str, netConfig: str, removeAllFirst: bool):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    setup_DBus_Supplicant_Access(interface)

    networkPath = ""
    selectErr = ""
    bssid = ""

    global selectedNetworkSSID
    selectedNetworkSSID = []
    global supplicantState
    supplicantState = []
    # global selectedBSSID
    # selectedBSSID = []
    global connectionEvents
    connectionEvents = []

    # Remove all configured networks and apply the new network
    if removeAllFirst:
        netw = iface.RemoveAllNetworks()

    netConfig_DBUS = dbus.Dictionary(json.loads(netConfig), signature='sv')
    netw = iface.AddNetwork(netConfig_DBUS)

    if netw != '/':
        # A valid network entry has been created - get the Index
        networkPath = netw.split("/")[-1]

        bus.add_signal_receiver(networkSelected,
        dbus_interface=WPAS_DBUS_INTERFACES_INTERFACE,
        signal_name="NetworkSelected")

        bus.add_signal_receiver(propertiesChanged,
            dbus_interface=WPAS_DBUS_INTERFACES_INTERFACE,
            signal_name="PropertiesChanged")

        # Select this network using its full path name
        selectErr = iface.SelectNetwork(netw)
        # time.sleep(10)

        if selectErr == None:
            # The network selection has been successsfully applied (does not mean a network is selected)
            main_context = GLib.MainContext.default()
            timeout_check = 0
            while supplicantState == [] and timeout_check <= API_TIMEOUT:
                time.sleep(1)
                timeout_check += 1
                # print (timeout_check)
                main_context.iteration(False)  
            
            if supplicantState != []:
                if supplicantState[0] == 'completed':
                	# Now fetch the current connected BSSID
                    print("About to check current BSS")
                    # bssid = fetch_currentBSS(interface)
                    bssidPath = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'CurrentBSS', dbus_interface=dbus.PROPERTIES_IFACE)
                    if bssidPath != '/':
                        bssid = getBss(bssidPath)
            # print("Selected BSSID: %s", bssid)
            # print("States : %s", connectionEvents)

    NetworkSetupDict = {
        "netId": networkPath,
        "selectErr": str(selectErr),
        "connectedNet": bssid,
        "input": netConfig
    }

    # print("Returning current BSS %s",NetworkSetupDict)

    return NetworkSetupDict
    #return json.loads('{"netId": "0", "selectErr": "None", "bssidPath": "5468"}')


async def get_systemd_network_currentNetwork_details(interface):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    res = ""
    setup_DBus_Supplicant_Access(interface)
    time.sleep(5)
    # res = fetch_currentBSS(interface)
    bssidPath = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'CurrentBSS', dbus_interface=dbus.PROPERTIES_IFACE)
    if bssidPath != '/':
        res = getBss(bssidPath)
        return {"connectedNet":res}
    else:
        return {"connectedNet":{"ssid": "", "bssid": "", "wpa": "", "wpa2": "", "signal": 0, "freq": 0}}

# async def main():
#     # await get_async_systemd_network_scan('passive', 'wlan0')
#     testnet = '{"ssid":"PiAP_6","psk":"wlanpieea","key_mgmt":"SAE","ieee80211w":2}'
#     await set_systemd_network_addNetwork('wlan0',testnet,True)
    
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
