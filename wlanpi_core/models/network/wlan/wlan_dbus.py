import logging

import dbus

from wlanpi_core.constants import (
    API_DEFAULT_TIMEOUT,
    WPAS_DBUS_INTERFACE,
    WPAS_DBUS_INTERFACES_INTERFACE,
    WPAS_DBUS_OPATH,
    WPAS_DBUS_SERVICE,
)
from wlanpi_core.models.network.wlan.exceptions import WlanDBUSInterfaceException
from wlanpi_core.models.network.wlan.wlan_dbus_interface import WlanDBUSInterface
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.network import list_wlan_interfaces


class WlanDBUS:

    DBUS_IFACE = dbus.PROPERTIES_IFACE
    DEFAULT_TIMEOUT = API_DEFAULT_TIMEOUT

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        self.default_timeout = API_DEFAULT_TIMEOUT

        self.main_dbus_loop = dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        self.bus = dbus.SystemBus(mainloop=self.main_dbus_loop)
        self.wpa_supplicant_proxy = self.bus.get_object(
            WPAS_DBUS_SERVICE, WPAS_DBUS_OPATH
        )
        self.wpa_supplicant = dbus.Interface(
            self.wpa_supplicant_proxy, WPAS_DBUS_INTERFACE
        )
        self.wpas = self.wpa_supplicant
        # setup_DBus_Supplicant_Access(interface)
        self.interfaces = {}

    def get_interface(self, interface) -> WlanDBUSInterface:
        if not interface in self.interfaces:
            new_interface = WlanDBUSInterface(
                wpa_supplicant=self.wpa_supplicant,
                system_bus=self.bus,
                interface_name=interface,
                default_timeout=self.DEFAULT_TIMEOUT,
            )
            self.interfaces[interface] = new_interface
        return self.interfaces[interface]

    def fetch_interfaces(self, wpas_obj):
        available_interfaces = []
        for system_interface in list_wlan_interfaces():
            try:
                self.get_interface(system_interface)
            except WlanDBUSInterfaceException as e:
                self.logger.warning(
                    f"Error trying to optimistically register interface {system_interface}: {e}"
                )

        ifaces = wpas_obj.Get(
            WPAS_DBUS_INTERFACE, "Interfaces", dbus_interface=self.DBUS_IFACE
        )
        self.logger.debug("InterfacesRequested: %s" % ifaces)
        for path in ifaces:
            self.logger.debug("Resolving Interface Path: %s" % path)
            if_obj = self.bus.get_object(WPAS_DBUS_SERVICE, path)
            ifname = if_obj.Get(
                WPAS_DBUS_INTERFACES_INTERFACE,
                "Ifname",
                dbus_interface=dbus.PROPERTIES_IFACE,
            )
            available_interfaces.append({"interface": ifname})
            self.logger.debug(f"Found interface : {ifname}")
        return available_interfaces

    def get_systemd_network_interfaces(self, timeout: int = DEFAULT_TIMEOUT):
        """
        Queries systemd via dbus to get a list of the available interfaces.
        """

        wpas_obj = self.bus.get_object(WPAS_DBUS_SERVICE, WPAS_DBUS_OPATH)
        self.logger.debug("Checking available interfaces")
        available_interfaces = self.fetch_interfaces(wpas_obj)
        self.logger.debug(f"Available interfaces: {available_interfaces}")
        return available_interfaces
