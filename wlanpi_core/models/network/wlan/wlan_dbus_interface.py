import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Union

import dbus.proxies
from dbus import DBusException, Interface, SystemBus
from dbus.proxies import ProxyObject
from gi.repository import GLib

from wlanpi_core.constants import (
    WPAS_DBUS_BSS_INTERFACE,
    WPAS_DBUS_INTERFACES_INTERFACE,
    WPAS_DBUS_SERVICE,
)
from wlanpi_core.models.network.wlan.exceptions import (
    WDIAuthenticationError,
    WDIConnectionException,
    WDIDisconnectedException,
    WDIScanError,
    WlanDBUSInterfaceCreationError,
    WlanDBUSInterfaceException,
)
from wlanpi_core.schemas.network import (
    NetworkSetupStatus,
    ScanResults,
    WlanConfig,
    network,
)
from wlanpi_core.schemas.network.network import SupplicantNetwork
from wlanpi_core.utils.g_lib_loop import GLibLoop
from wlanpi_core.utils.general import byte_array_to_string
from wlanpi_core.utils.network import (
    add_default_route,
    get_ip_address,
    remove_default_routes,
    renew_dhcp,
)


class WlanDBUSInterface:
    ALLOWED_SCAN_TYPES = [
        "active",
        "passive",
    ]
    DBUS_IFACE = dbus.PROPERTIES_IFACE

    def __init__(
        self,
        wpa_supplicant: dbus.proxies.Interface,
        system_bus: SystemBus,
        interface_name: str,
        default_timeout: int = 20,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")
        print(f"Class is {__name__}")
        self.wpa_supplicant: Interface = wpa_supplicant
        self.interface_name: str = interface_name
        self.system_bus: SystemBus = system_bus
        self.default_timeout = default_timeout

        self.interface_dbus_path = None
        self.logger.debug(f"Getting interface {interface_name}")
        try:
            self.interface_dbus_path = self.wpa_supplicant.GetInterface(
                self.interface_name
            )
        except dbus.DBusException as exc:
            if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceUnknown:"):
                raise WlanDBUSInterfaceCreationError(
                    f"Interface unknown : {exc}"
                ) from exc
            try:
                self.interface_dbus_path = self.wpa_supplicant.CreateInterface(
                    {"Ifname": self.interface_name, "Driver": "nl80211"}
                )
                time.sleep(1)
            except dbus.DBusException as exc:
                if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceExists:"):
                    raise WlanDBUSInterfaceCreationError(
                        f"Interface cannot be created : {exc}"
                    ) from exc
        time.sleep(1)
        self.logger.debug(f"Interface path: {self.interface_dbus_path}")
        self.supplicant_dbus_object = self.system_bus.get_object(
            WPAS_DBUS_SERVICE, self.interface_dbus_path
        )
        self.supplicant_dbus_interface = dbus.Interface(
            self.supplicant_dbus_object, WPAS_DBUS_INTERFACES_INTERFACE
        )

        # Transient vars
        self.last_scan = None

    def _get_dbus_object(self, object_path: str) -> ProxyObject:
        return self.system_bus.get_object(WPAS_DBUS_SERVICE, object_path)

    def _get_from_wpa_supplicant_network(self, bss: str, key: str) -> any:
        net_obj = self.system_bus.get_object(WPAS_DBUS_SERVICE, bss)
        return net_obj.Get(WPAS_DBUS_BSS_INTERFACE, key, dbus_interface=self.DBUS_IFACE)

    def _get_from_wpa_supplicant_interface(self, key: str) -> any:
        return self.supplicant_dbus_object.Get(
            WPAS_DBUS_INTERFACES_INTERFACE, key, dbus_interface=dbus.PROPERTIES_IFACE
        )

    def _get_bssid_path(self) -> str:
        return self._get_from_wpa_supplicant_interface("CurrentBSS")

    def get_bss(self, bss) -> dict[str, any]:
        """
        Queries DBUS_BSS_INTERFACE through dbus for a BSS Path

        Example path: /fi/w1/wpa_supplicant1/Interfaces/0/BSSs/567
        """

        try:
            # Get the BSSID from the byte array
            val = self._get_from_wpa_supplicant_network(bss, "BSSID")
            bssid = ""
            for item in val:
                bssid = bssid + ":%02x" % item
            bssid = bssid[1:]

            # Get the SSID from the byte array
            ssid = byte_array_to_string(
                self._get_from_wpa_supplicant_network(bss, "SSID")
            )

            # # Get the WPA Type from the byte array
            # val = self._get_from_wpa_supplicant_network(bss, "WPA")
            # if len(val["KeyMgmt"]) > 0:
            #     pass

            # Get the RSN Info from the byte array
            val = self._get_from_wpa_supplicant_network(bss, "RSN")
            key_mgmt = "/".join([str(r) for r in val["KeyMgmt"]])

            # Get the Frequency from the byte array
            freq = self._get_from_wpa_supplicant_network(bss, "Frequency")

            # Get the RSSI from the byte array
            signal = self._get_from_wpa_supplicant_network(bss, "Signal")

            # Get the Phy Rates from the byte array
            rates = self._get_from_wpa_supplicant_network(bss, "Rates")
            min_rate = min(rates) if len(rates) > 0 else 0

            # # Get the IEs from the byte array
            # ies = self._get_from_wpa_supplicant_network(bss, "IEs")
            # self.logger.debug(f"IEs: {ies}")

            return {
                "ssid": ssid,
                "bssid": bssid,
                "key_mgmt": key_mgmt,
                "signal": signal,
                "freq": freq,
                "minrate": min_rate,
            }

        except DBusException as e:
            raise WlanDBUSInterfaceException() from e
        except ValueError as error:
            raise WlanDBUSInterfaceException(error) from error

    def pretty_print_bss(self, bss_path) -> str:
        bss_details = self.get_bss(bss_path)
        if bss_details:
            ssid = bss_details["ssid"] if bss_details["ssid"] else "<hidden>"
            bssid = bss_details["bssid"]
            freq = bss_details["freq"]
            rssi = bss_details["signal"]
            key_mgmt = bss_details["key_mgmt"]
            minrate = bss_details["minrate"]

            result = f"[{bssid}] {freq}, {rssi}dBm, {minrate} | {ssid} [{key_mgmt}] "
            return result
        else:
            return f"BSS Path {bss_path} could not be resolved"

    def get_current_network_details(
        self,
    ) -> dict[str, Optional[dict[str, Union[str, int]]]]:
        try:

            bssid_path = self._get_bssid_path()

            if bssid_path != "/":
                res = self.get_bss(bssid_path)
                return {"connectedStatus": True, "connectedNet": res}
            else:
                return {"connectedStatus": False, "connectedNet": None}
        except DBusException as err:
            self.logger.error(f"DBUS error while getting BSSID: {str(err)}")
            raise WlanDBUSInterfaceException(
                f"DBUS error while getting BSSID: {str(err)}"
            ) from err

    async def get_network_scan(
        self, scan_type: str, timeout: Optional[int] = None
    ) -> ScanResults:
        self.logger.info("Starting network scan...")
        if not timeout:
            timeout = self.default_timeout
        if scan_type not in self.ALLOWED_SCAN_TYPES:
            raise ValueError("Invalid scan type")

        scan_config = dbus.Dictionary({"Type": scan_type}, signature="sv")

        # Get a handle for the main loop so we can start and stop it
        with GLibLoop() as glib_loop:
            # Create a new Future object to manage the async execution.
            async_loop = asyncio.get_running_loop()
            done_future = async_loop.create_future()

            def timeout_handler(*args):
                done_future.set_exception(
                    TimeoutError(f"Scan timed out after {timeout} seconds: {args}")
                )
                glib_loop.finish()

            def done_handler(success):
                self.logger.debug(f"Scan done: success={success}")
                # global scan
                local_scan = []
                res = self._get_from_wpa_supplicant_interface("BSSs")
                self.logger.debug("Scanned wireless networks:")
                for opath in res:
                    bss = self.get_bss(opath)
                    if bss:
                        local_scan.append(bss)
                self.last_scan = local_scan
                self.logger.debug(
                    f"A Scan has completed with {len(local_scan)} results",
                )
                self.logger.debug(local_scan)
                done_future.set_result(local_scan)
                glib_loop.finish()

            try:
                scan_handler = self.system_bus.add_signal_receiver(
                    done_handler,
                    dbus_interface=WPAS_DBUS_INTERFACES_INTERFACE,
                    signal_name="ScanDone",
                )

                # Start Scan
                self.supplicant_dbus_interface.Scan(scan_config)
                # exit after waiting a short time for the signal
                glib_loop.start_timeout(seconds=timeout, callback=timeout_handler)

                glib_loop.run()
                scan_results = await done_future
            except (TimeoutError, GLib.Error, DBusException) as e:
                self.logger.warning("Error while scanning: %s", e)
                raise WDIScanError from e
            finally:
                scan_handler.remove()
        return scan_results

    async def add_network(
        self,
        wlan_config: WlanConfig,
        remove_others: bool = False,
        timeout: Optional[int] = None,
    ) -> NetworkSetupStatus:
        if not timeout:
            timeout = self.default_timeout
        self.logger.info(
            "Configuring WLAN on %s with config: %s", self.interface_name, wlan_config
        )

        # Create a new Future object to manage the async execution.
        async_loop = asyncio.get_running_loop()
        add_network_future = async_loop.create_future()

        response = network.NetworkSetupLog(selectErr="", eventLog=[])

        self.logger.debug("Configuring DBUS interface")

        connection_events = []

        # Get a handle for the main loop so we can start and stop it
        with GLibLoop() as glib_loop:

            def timeout_callback(*args):
                add_network_future.set_exception(
                    TimeoutError(
                        f"Connection timed out after {timeout} seconds: {args}"
                    )
                )
                glib_loop.finish()

            def network_selected_callback(selected_network):
                self.logger.info(f"Network Selected (Signal) : {selected_network}")

            def properties_changed_callback(properties):
                self.logger.debug(f"PropertiesChanged: {properties}")

                state = properties.get("State", None)
                disconnect_reason = properties.get("DisconnectReason", None)
                if state:
                    if state == "completed":
                        time.sleep(2)
                        # Is sleeping here really the answer?
                        if self.interface_name:
                            remove_default_routes(interface=self.interface_name)
                            renew_dhcp(self.interface_name)
                            add_default_route(interface=self.interface_name)
                            ipaddr = get_ip_address(self.interface_name)
                            connection_events.append(
                                network.NetworkEvent(
                                    event=f"IP Address {ipaddr} on {self.interface_name}",
                                    time=f"{datetime.now()}",
                                )
                            )
                        self.logger.debug(f"Connection Completed: State: {state}")
                        # End
                        add_network_future.set_result(state)
                        glib_loop.finish()
                    elif state == "4way_handshake":
                        self.logger.debug(f"PropertiesChanged: State: {state}")
                        if properties.get("CurrentBSS"):
                            self.logger.debug(
                                f"Handshake attempt to: {self.pretty_print_bss(properties['CurrentBSS'])}"
                            )
                    else:
                        self.logger.debug(f"PropertiesChanged: State: {state}")
                    connection_events.append(
                        network.NetworkEvent(event=f"{state}", time=f"{datetime.now()}")
                    )
                elif disconnect_reason:
                    self.logger.debug(f"Disconnect Reason: {disconnect_reason}")
                    if disconnect_reason:
                        if disconnect_reason in [3, -3]:
                            connection_events.append(
                                network.NetworkEvent(
                                    event="Station is Leaving", time=f"{datetime.now()}"
                                )
                            )
                        elif disconnect_reason == 15:
                            event = network.NetworkEvent(
                                event="4-Way Handshake Fail (check password)",
                                time=f"{datetime.now()}",
                            )
                            connection_events.append(event)
                            # End
                            add_network_future.set_exception(
                                WDIAuthenticationError(event)
                            )
                            glib_loop.finish()
                        else:
                            event = network.NetworkEvent(
                                event=f"Error: Disconnected [{disconnect_reason}]",
                                time=f"{datetime.now()}",
                            )
                            connection_events.append(event)
                            add_network_future.set_exception(
                                WDIDisconnectedException(event)
                            )
                            glib_loop.finish()

                # For debugging purposes only
                # if properties.get("BSSs") is not None:
                #     print("Supplicant has found the following BSSs")
                #     for BSS in properties["BSSs"]:
                #         if len(BSS) > 0:
                #             print(pretty_print_BSS(BSS))

                current_auth_mode = properties.get("CurrentAuthMode")
                if current_auth_mode is not None:
                    self.logger.debug(f"Current Auth Mode is {current_auth_mode}")

                auth_status = properties.get("AuthStatusCode")
                if auth_status is not None:
                    self.logger.debug(f"Auth Status: {auth_status}")
                    if auth_status == 0:
                        connection_events.append(
                            network.NetworkEvent(
                                event="authenticated", time=f"{datetime.now()}"
                            )
                        )
                    else:
                        connection_events.append(
                            network.NetworkEvent(
                                event=f"authentication failed with code {auth_status}",
                                time=f"{datetime.now()}",
                            )
                        )

            select_err = None
            bssid = None
            try:
                network_change_handler = self.system_bus.add_signal_receiver(
                    network_selected_callback,
                    dbus_interface=WPAS_DBUS_INTERFACES_INTERFACE,
                    signal_name="NetworkSelected",
                )

                properties_change_handler = self.system_bus.add_signal_receiver(
                    properties_changed_callback,
                    dbus_interface=WPAS_DBUS_INTERFACES_INTERFACE,
                    signal_name="PropertiesChanged",
                )

                # Remove all other connections if requested
                if remove_others:
                    self.logger.info("Removing existing connections")
                    self.supplicant_dbus_interface.RemoveAllNetworks()

                wlan_config_cleaned = {k: v for k, v in wlan_config if v is not None}
                wlan_config_dbus = dbus.Dictionary(wlan_config_cleaned, signature="sv")
                netw = self.supplicant_dbus_interface.AddNetwork(wlan_config_dbus)

                if netw != "/":
                    self.logger.debug("Valid network entry received")

                    # Select this network using its full path name
                    select_err = self.supplicant_dbus_interface.SelectNetwork(netw)
                    self.logger.debug(f"Network selected with result: {select_err}")

                    self.logger.debug(f"Logged connection Events: {connection_events}")
                    if select_err is None:
                        # exit after waiting a short time for the signal
                        glib_loop.start_timeout(
                            seconds=timeout, callback=timeout_callback
                        )
                        # The network selection has been successfully applied (does not mean a network is selected)
                        glib_loop.run()

                        try:
                            connect_result = await add_network_future
                        except WDIConnectionException as err:
                            self.logger.error(f"Failed to connect: {err}")
                            connect_result = None

                        if connect_result == "completed":
                            self.logger.info(
                                "Connection to network completed. Verifying connection..."
                            )

                            # Check the current BSSID post connection
                            bssid_path = self._get_bssid_path()
                            if bssid_path != "/":
                                bssid = self.get_bss(bssid_path)
                                self.logger.debug(f"Logged Events: {connection_events}")
                                if bssid:
                                    self.logger.info("Connected")
                                    status = "connected"
                                else:
                                    self.logger.warning(
                                        "Connection failed. Post connection check returned no network"
                                    )
                                    status = "connection_lost"
                            else:

                                self.logger.warning("Connection failed. Aborting")
                                status = "connection_lost"
                        else:
                            self.logger.warning("Connection failed. Aborting")
                            status = f"connection failed:{connect_result}"

            except DBusException as de:
                self.logger.error(f"DBUS Error State: {de}", 0)
                # raise WlanDBUSInterfaceException from de
            finally:
                if network_change_handler:
                    network_change_handler.remove()
                if properties_change_handler:
                    properties_change_handler.remove()

        response.eventLog = connection_events
        if select_err and select_err is not None:
            response.selectErr = str(select_err)
        else:
            response.selectErr = ""

        return {
            "status": status,
            "response": response,
            "connectedNet": bssid,
            "input": wlan_config.ssid,
        }

    def disconnect(self) -> None:
        """Disconnects the given interface from any network it may be associated with"""
        self.logger.info("Disconnecting WLAN on %s", self.interface_name)
        self.supplicant_dbus_interface.Disconnect()

    def remove_all_networks(self) -> None:
        """Removes all networks from the interface"""
        self.logger.info("Removing all Networks onon %s", self.interface_name)
        self.supplicant_dbus_interface.RemoveAllNetworks()

    def remove_network(self, network_id: int) -> None:
        """Removes a single network from the interface"""
        self.logger.info("Removing network %s on %s", network_id, self.interface_name)
        self.supplicant_dbus_interface.RemoveNetwork(
            f"{self.interface_dbus_path}/Networks/{network_id}"
        )

    def networks(self) -> dict[int, SupplicantNetwork]:
        """Returns a list of available networks"""
        networks = {}
        for network_path in self._get_from_wpa_supplicant_interface("Networks"):
            networks[int(network_path.split("/")[-1])] = self._get_dbus_object(
                network_path
            ).Get(
                "fi.w1.wpa_supplicant1.Network",
                "Properties",
                dbus_interface=dbus.PROPERTIES_IFACE,
            )
        return networks

    def get_network(self, network_id: int) -> SupplicantNetwork:
        """Returns a list of available networks"""
        return self._get_dbus_object(
            f"{self.interface_dbus_path}/Networks/{network_id}"
        ).Get(
            "fi.w1.wpa_supplicant1.Network",
            "Properties",
            dbus_interface=dbus.PROPERTIES_IFACE,
        )

    def current_network(
        self,
    ) -> Optional[SupplicantNetwork]:
        """Returns the currently selected network, if any"""
        net_path = self._get_from_wpa_supplicant_interface("CurrentNetwork")
        if net_path == "/":
            return None
        return self._get_dbus_object(net_path).Get(
            "fi.w1.wpa_supplicant1.Network",
            "Properties",
            dbus_interface=dbus.PROPERTIES_IFACE,
        )
