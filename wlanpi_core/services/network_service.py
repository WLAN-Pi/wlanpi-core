from wlanpi_core.models.validation_error import ValidationError
import dbus
from dbus import Boolean, Interface, SystemBus, Dictionary
from dbus.exceptions import DBusException
import sys
import time
import json

WPAS_DBUS_SERVICE = "fi.w1.wpa_supplicant1"
WPAS_DBUS_INTERFACE = "fi.w1.wpa_supplicant1"
WPAS_DBUS_OPATH = "/fi/w1/wpa_supplicant1"
WPAS_DBUS_INTERFACES_INTERFACE = "fi.w1.wpa_supplicant1.Interface"
WPAS_DBUS_INTERFACES_OPATH = "/fi/w1/wpa_supplicant1/Interfaces"
WPAS_DBUS_BSS_INTERFACE = "fi.w1.wpa_supplicant1.BSS"
WPAS_DBUS_NETWORK_INTERFACE = "fi.w1.wpa_supplicant1.Network"

allowed_scan_types = [
    "active",
    "passive",
]

def is_allowed_scan_type(scan: str):
    for allowed_scan_type in allowed_scan_types:
        if scan == allowed_scan_type:
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

def showNetwork(net):
	net_obj = bus.get_object(WPAS_DBUS_SERVICE, net)
	net = dbus.Interface(net_obj, WPAS_DBUS_NETWORK_INTERFACE)
	enabled = net_obj.Get(WPAS_DBUS_NETWORK_INTERFACE, 'Enabled',
			  dbus_interface=dbus.PROPERTIES_IFACE)
	network_properties = net_obj.Get(WPAS_DBUS_NETWORK_INTERFACE, 'Properties',
			  dbus_interface=dbus.PROPERTIES_IFACE)

	print("Net %s BSSID: %s Key: %s [Enabled: %s]" % (network_properties.get('ssid',''), network_properties.get('bssid',''), network_properties.get('key_mgmt',''), enabled))

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

bus = SystemBus()
systemd = bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
manager = Interface(systemd, dbus_interface="org.freedesktop.systemd1.Manager")

proxy = bus.get_object('fi.w1.wpa_supplicant1','/fi/w1/wpa_supplicant1')
wpas = Interface(proxy, 'fi.w1.wpa_supplicant1')
path = wpas.GetInterface('wlan0')

# print(proxy.Interfaces)


#adapters_name = props_iface.Get("fi.w1.wpa_supplicant1.Interface", "Ifname")

# print(interfaces)
#print ("Interface's name is", adapters_name)

props_iface = Interface(proxy, "org.freedesktop.DBus.Properties")
interfaces = props_iface.Get('fi.w1.wpa_supplicant1', "Interfaces")

try:
	interface = interfaces[0]
except IndexError:
	sys.exit("No interfaces availible")


network_test_6G = dbus.Dictionary({
    'ssid': 'PiAP_6',
    'psk': 'wlanpieea',
	'key_mgmt' : 'SAE',
	'ieee80211w' : 2
    }, signature='sv')




# print("Scanned wireless networks:")
# for opath in res:
# 	#print(opath)
# 	getBss(opath)

# res = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'Networks', dbus_interface=dbus.PROPERTIES_IFACE)
# print("Configured wireless networks:")
# for opath in res:
# 	print(opath)
# 	showNetwork(opath)

# res = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'CurrentNetwork', dbus_interface=dbus.PROPERTIES_IFACE)
# print("Configured network in use:")
# print(res)
# #	showNetwork(opath)


async def get_systemd_network_scan(type: str):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """

    scan = []
    type = type.strip().lower()
    if is_allowed_scan_type(type):
		#use these to run commands on the interface
        interface_obj = bus.get_object(WPAS_DBUS_SERVICE, interface)
        interface_interface = Interface(interface_obj, WPAS_DBUS_INTERFACES_INTERFACE)

        if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
        res = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'BSSs', dbus_interface=dbus.PROPERTIES_IFACE)

        scanConfig = dbus.Dictionary({
            'Type': type
		}, signature='sv')

        netw = interface_interface.Scan(scanConfig)
        time.sleep(5)

        for opath in res:
            scan.append(getBss(opath))

        return {"nets": scan}

    raise ValidationError(
        f"{type} is not a valid scan type", status_code=400
    )


async def set_systemd_network_addNetwork(netConfig: str, removeAllFirst: bool):
    """
    Queries systemd via dbus to get a scan of the available networks.
    """
    status = ""
    scan = []

	#netw = interface_interface.SignalPoll()
    #print(netw)


    #use these to run commands on the interface
    interface_obj = bus.get_object(WPAS_DBUS_SERVICE, interface)
    interface_interface = Interface(interface_obj, WPAS_DBUS_INTERFACES_INTERFACE)


    netw = interface_interface.RemoveAllNetworks()
    netw = interface_interface.AddNetwork(network_test_6G)
    interface_interface.SelectNetwork(netw)

    if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
    res = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'BSSs', dbus_interface=dbus.PROPERTIES_IFACE)
    
    for opath in res:
        scan = scan + getBss(opath)

    return scan


async def get_systemd_network_currentNetwork_details():
    """
    Queries systemd via dbus to get a scan of the available networks.
    """
    status = ""
    scan = []

    if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
    res = if_obj.Get(WPAS_DBUS_INTERFACES_INTERFACE, 'BSSs', dbus_interface=dbus.PROPERTIES_IFACE)
    
    for opath in res:
        scan.append(getBss(opath))

    return scan
