"""Legacy DBus and wpa_supplicant network service layer."""

import asyncio
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

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
    """Asyncio-friendly D-Bus wrapper that polls instead of using signals (no PyGObject)."""

    def __init__(self) -> None:
        self._bus: Any = None
        self._bus_lock = threading.Lock()

    @property
    def bus(self) -> Any:
        """Open the system bus only when a D-Bus operation is requested."""
        if self._bus is None:
            with self._bus_lock:
                if self._bus is None:
                    self._bus = dbus.SystemBus()
        return self._bus

    async def poll_until_condition(
        self,
        condition_func: Callable[[], bool],
        timeout: int = 20,
        initial_interval: float = 0.1,
        max_interval: float = 0.5,
    ) -> bool:
        """Poll condition_func with a growing interval; return False after `timeout` seconds."""
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
    ) -> Any:
        """Return a property of a D-Bus object."""
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
        *args: Any,
    ) -> Any:
        """Call a method on a D-Bus object and return its result."""
        obj = self.bus.get_object(service_name, object_path)
        method = obj.get_dbus_method(method_name, interface_name)
        return method(*args)


DBUS_MANAGER = AsyncDBusManager()

API_TIMEOUT = 20

bus: Any = None
if_obj: Any = None
iface: Any = None
wpas: Any = None
scan: list[Any] = []
currentInterface: str | None = None
connectionEvents: list[Any] = []
supplicantState: list[Any] = []
selectedNetworkSSID: list[Any] = []

DEBUG_LEVEL = 1


def set_debug_level(level: int) -> None:
    """Set the global debug level (0 prints nothing, 3 prints everything)."""
    global DEBUG_LEVEL
    DEBUG_LEVEL = level


def debug_print(message: Any, level: int) -> None:
    """Print `message` when `level` is at or below the global debug level."""
    if level <= DEBUG_LEVEL:
        print(message)


allowed_scan_types = [
    "active",
    "passive",
]


def is_allowed_scan_type(scan: str) -> bool:
    """Check whether the scan type is allowed."""
    for allowed_scan_type in allowed_scan_types:
        if scan == allowed_scan_type:
            return True
    return False


def is_allowed_interface(interface: str, wpas_obj: Any) -> bool:
    """Check whether the interface is among the available ones."""
    available_interfaces = fetch_interfaces(wpas_obj)
    for allowed_interface in available_interfaces:
        if interface == allowed_interface:
            return True
    return False


def byte_array_to_string(s: Any) -> str:
    """Convert a dbus byte array to a printable string."""
    r = ""
    for c in s:
        if c >= 32 and c < 127:
            r += chr(c)
        else:
            r += " "
    return r


def renew_dhcp(interface: str) -> None:
    """Use dhclient to release and request a new DHCP lease."""
    try:
        run_command(["sudo", "dhclient", "-r", interface], raise_on_fail=True)
        time.sleep(3)
        run_command(["sudo", "dhclient", interface], raise_on_fail=True)
    except RunCommandError as err:
        debug_print(
            f"Failed to renew DHCP. Code:{err.return_code}, Error: {err.error_msg}", 1
        )


def get_ip_address(interface: str) -> str | None:
    """Extract the IP Address from the linux ip add show <if> command."""
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
        return None


def getBss(bss: str) -> dict[str, Any] | None:
    """Return SSID, BSSID, key_mgmt, signal, freq and minrate for a wpa_supplicant BSS path."""

    try:
        net_obj = bus.get_object(WPAS_DBUS_SERVICE, bss)

        val = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "BSSID", dbus_interface=dbus.PROPERTIES_IFACE
        )
        bssid = ""
        for item in val:
            bssid = bssid + f":{item:02x}"
        bssid = bssid[1:]

        val = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "SSID", dbus_interface=dbus.PROPERTIES_IFACE
        )
        ssid = byte_array_to_string(val)

        val = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "WPA", dbus_interface=dbus.PROPERTIES_IFACE
        )
        if len(val["KeyMgmt"]) > 0:
            pass

        val = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "RSN", dbus_interface=dbus.PROPERTIES_IFACE
        )
        key_mgmt = "/".join([str(r) for r in val["KeyMgmt"]])

        freq = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "Frequency", dbus_interface=dbus.PROPERTIES_IFACE
        )

        signal = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "Signal", dbus_interface=dbus.PROPERTIES_IFACE
        )

        rates = net_obj.Get(
            WPAS_DBUS_BSS_INTERFACE, "Rates", dbus_interface=dbus.PROPERTIES_IFACE
        )

        minrate = 0
        if len(rates) > 0:
            minrate = rates[-1]

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
        raise ValidationError(f"{error}", status_code=400) from None


def pretty_print_BSS(BSSPath: str) -> str:
    """Return a human-readable summary of a BSS path."""
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


def fetch_interfaces(wpas_obj: Any) -> list[dict[str, Any]]:
    """Return the interfaces known to wpa_supplicant."""
    available_interfaces = []
    ifaces = wpas_obj.Get(
        WPAS_DBUS_INTERFACE, "Interfaces", dbus_interface=dbus.PROPERTIES_IFACE
    )
    debug_print(f"InterfacesRequested: {ifaces}", 2)
    for path in ifaces:
        debug_print(f"Resolving Interface Path: {path}", 2)
        if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
        ifname = if_obj.Get(
            WPAS_DBUS_INTERFACES_INTERFACE,
            "Ifname",
            dbus_interface=dbus.PROPERTIES_IFACE,
        )
        available_interfaces.append({"interface": ifname})
        debug_print(f"Found interface : {ifname}", 2)
    return available_interfaces


def fetch_currentBSS(interface: str) -> Any:
    """Return the current BSS details for an interface."""
    bssid: Any = ""

    try:
        path = wpas.GetInterface(interface)
    except dbus.DBusException as exc:
        if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceUnknown:"):
            raise ValidationError(
                f"Interface unknown : {exc}", status_code=400
            ) from None
        try:
            path = wpas.CreateInterface({"Ifname": interface, "Driver": "test"})
            time.sleep(1)
        except dbus.DBusException as exc:
            if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceExists:"):
                raise ValidationError(
                    f"Interface cannot be created : {exc}", status_code=400
                ) from None

    time.sleep(1)

    if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
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


def scanDone(success: bool) -> None:
    """Handle the scan done signal and store the results."""
    debug_print(f"Scan done: success={success}", 1)
    global scan
    local_scan: list[Any] = []
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


def networkSelected(network: Any) -> None:
    """Record the selected network path."""
    debug_print(f"Network Selected (Signal) : {network}", 1)
    selectedNetworkSSID.append(network)


def propertiesChanged(properties: Any) -> None:
    """Handle wpa_supplicant properties-changed signals."""
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
            debug_print("SCAN---", 3)
        elif state == "associating":
            debug_print(f"PropertiesChanged: {state}", 1)
        elif state == "authenticating":
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


def setup_DBus_Supplicant_Access(interface: str) -> None:
    """Set up the dbus connection to wpa_supplicant."""
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
            raise ValidationError(
                f"Interface unknown : {exc}", status_code=400
            ) from None
        try:
            path = wpas.CreateInterface({"Ifname": interface, "Driver": "test"})
            time.sleep(1)
        except dbus.DBusException as exc:
            if not str(exc).startswith("fi.w1.wpa_supplicant1.InterfaceExists:"):
                raise ValidationError(
                    f"Interface cannot be created : {exc}", status_code=400
                ) from None
    time.sleep(1)
    debug_print(path, 3)
    if_obj = bus.get_object(WPAS_DBUS_SERVICE, path)
    iface = dbus.Interface(if_obj, WPAS_DBUS_INTERFACES_INTERFACE)


async def get_systemd_network_interfaces(
    timeout: network.APIConfig,
) -> dict[str, Any]:
    """Query systemd via dbus to get a list of the available interfaces."""
    global bus
    bus = dbus.SystemBus()
    wpas_obj = bus.get_object(WPAS_DBUS_SERVICE, WPAS_DBUS_OPATH)
    debug_print("Checking available interfaces", 3)
    available_interfaces = fetch_interfaces(wpas_obj)
    debug_print(f"Available interfaces: {available_interfaces}", 3)
    return {"interfaces": available_interfaces}


async def get_async_systemd_network_scan(
    type: str, interface: network.Interface, timeout: network.APIConfig
) -> dict[str, Any]:
    """Query systemd via dbus to get a scan of the available networks."""

    type = type.strip().lower()
    if is_allowed_scan_type(type):
        try:
            setup_DBus_Supplicant_Access(interface.interface)

            global scan
            scan = []
            scanConfig = dbus.Dictionary({"Type": type}, signature="sv")

            iface.Scan(scanConfig)

            scan_successful = await DBUS_MANAGER.poll_until_condition(
                lambda: collect_scan_results(), timeout=timeout.timeout
            )

            if not scan_successful:
                return {"nets": []}

            return {"nets": scan}
        except DBusException as de:
            debug_print(f"DBUS Error State: {de}", 0)
        except ValueError as error:
            raise ValidationError(f"{error}", status_code=400) from None
    raise ValidationError(f"{type} is not a valid scan type", status_code=400)


def collect_scan_results() -> bool:
    """Store the current scan results globally; return True once there are any."""
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
) -> dict[str, Any]:
    """Use wpa_supplicant to connect to a WLAN network."""
    global selectedNetworkSSID
    selectedNetworkSSID = []
    global supplicantState
    supplicantState = []
    global connectionEvents
    connectionEvents = []

    API_TIMEOUT = timeout

    debug_print("Setting up supplicant access", 3)
    setup_DBus_Supplicant_Access(interface.interface)

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

        if removeAllFirst:
            debug_print("Removing existing connections", 2)
            netw = iface.RemoveAllNetworks()

        netConfig_cleaned = {k: v for k, v in netConfig if v is not None}
        netConfig_DBUS = dbus.Dictionary(netConfig_cleaned, signature="sv")
        netw = iface.AddNetwork(netConfig_DBUS)

        if netw != "/":
            debug_print("Valid network entry received", 2)
            netw.split("/")[-1]

            selectErr = iface.SelectNetwork(netw)
            debug_print(f"Network selected with result: {selectErr}", 2)

            if selectErr is None:
                connected = await monitor_connection_state(API_TIMEOUT.timeout)

                if connected:
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
        raise ValidationError(f"{error}", status_code=400) from None

    response.eventLog = connectionEvents
    if selectErr is not None:
        response.selectErr = str(selectErr)
    else:
        response.selectErr = ""

    return {
        "status": status,
        "response": response,
        "connectedNet": bssid,
        "input": netConfig.id,
    }


async def monitor_connection_state(timeout: int) -> bool:
    """Monitor connection state by polling."""
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
) -> dict[str, Any] | None:
    """Return whether `interface` is connected and its current BSS details."""
    try:
        res: Any = ""
        setup_DBus_Supplicant_Access(interface.interface)
        await asyncio.sleep(1)

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
        return None
    except ValueError as error:
        raise ValidationError(f"{error}", status_code=400) from None


if __name__ == "__main__":
    print(get_ip_address("eth0"))
