import logging
from pathlib import Path
from typing import Optional, Union

from wlanpi_core.constants import (
    APPS_FILE,
    DEFAULT_CONFIG_DIR,
    DEFAULT_CTRL_INTERFACE,
    DEFAULT_DHCP_DIR,
    PID_DIR,
    IW_FILE,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.schemas.network.network import (
    NamespaceConfig,
    NetConfig,
    NetworkEvent,
    NetworkModeEnum,
    NetworkSetupLog,
    NetworkSetupStatus,
    RootConfig,
    ScanItem,
    SecurityTypes,
)
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.namespace_execution import ns_exec
from wlanpi_core.utils.network_management import (
    restart_dhcp_with_timeout,
    set_default_route,
    write_dhcp_config,
)
from wlanpi_core.adapters import discovery, interface, phy
from wlanpi_core.namespaces import (
    apps,
    interfaces as ns_interfaces,
    namespace as ns_namespace,
    processes,
)
from wlanpi_core.connection.monitor import ConnectionMonitor, stop_all_connection_monitors, stop_connection_monitor
from wlanpi_core.wpa import (
    config as wpa_config,
    supplicant as wpa_supplicant,
    status as wpa_status,
)


class NetworkNamespaceService:
    def __init__(
        self,
        config_dir=DEFAULT_CONFIG_DIR,
        ctrl_interface=DEFAULT_CTRL_INTERFACE,
        dhcp_dir=DEFAULT_DHCP_DIR,
    ):
        self.config_dir = Path(config_dir)
        self.ctrl_interface = ctrl_interface
        self.dhcp_dir = Path(dhcp_dir)
        self.pid_dir = Path(PID_DIR)
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        
        # Fixed global settings
        self.global_settings = {
            "ctrl_interface": ctrl_interface,
            "update_config": 1,
        }
        
        self.log = logging.getLogger(__name__)
        self.event_log: list[NetworkEvent] = []
        
        # Connection monitoring is now handled by connection.monitor module

    def _validate_config(self, cfg: Union[NamespaceConfig, RootConfig]) -> tuple[bool, str]:
        """
        Comprehensive validation of config against schema before any state changes.
        Returns (is_valid, error_message)
        """
        errors = []
        
        # Required fields for RootConfig
        if not hasattr(cfg, 'interface') or not cfg.interface or not isinstance(cfg.interface, str):
            errors.append("interface is required and must be a non-empty string")
        elif not cfg.interface.strip():
            errors.append("interface cannot be empty or whitespace")
        
        if not hasattr(cfg, 'phy') or not cfg.phy or not isinstance(cfg.phy, str):
            errors.append("phy is required and must be a non-empty string")
        elif not cfg.phy.strip():
            errors.append("phy cannot be empty or whitespace")
        
        if not hasattr(cfg, 'iface_display_name') or not cfg.iface_display_name or not isinstance(cfg.iface_display_name, str):
            errors.append("iface_display_name is required and must be a non-empty string")
        elif not cfg.iface_display_name.strip():
            errors.append("iface_display_name cannot be empty or whitespace")
        
        # Mode validation
        if not hasattr(cfg, 'mode'):
            errors.append("mode is required")
        else:
            if not isinstance(cfg.mode, (str, NetworkModeEnum)):
                errors.append(f"mode must be a string or NetworkModeEnum, got {type(cfg.mode)}")
            else:
                mode_str = cfg.mode.value if isinstance(cfg.mode, NetworkModeEnum) else str(cfg.mode)
                if mode_str not in [e.value for e in NetworkModeEnum]:
                    errors.append(f"mode must be one of {[e.value for e in NetworkModeEnum]}, got '{mode_str}'")
        
        # NamespaceConfig specific validation
        if isinstance(cfg, NamespaceConfig):
            if not hasattr(cfg, 'namespace') or not cfg.namespace or not isinstance(cfg.namespace, str):
                errors.append("namespace is required for NamespaceConfig and must be a non-empty string")
            elif not cfg.namespace.strip():
                errors.append("namespace cannot be empty or whitespace")
        
        # Security validation if present
        if cfg.security is not None:
            if not hasattr(cfg.security, 'ssid') or not cfg.security.ssid or not isinstance(cfg.security.ssid, str):
                errors.append("security.ssid is required and must be a non-empty string when security is provided")
            elif not cfg.security.ssid.strip():
                errors.append("security.ssid cannot be empty or whitespace")
            
            if not hasattr(cfg.security, 'security') or cfg.security.security is None:
                errors.append("security.security is required when security is provided")
            else:
                if not isinstance(cfg.security.security, (str, SecurityTypes)):
                    errors.append(f"security.security must be a SecurityTypes enum or valid string, got {type(cfg.security.security)}")
                else:
                    sec_str = cfg.security.security.value if isinstance(cfg.security.security, SecurityTypes) else str(cfg.security.security)
                    valid_security = [e.value for e in SecurityTypes]
                    if sec_str not in valid_security:
                        errors.append(f"security.security must be one of {valid_security}, got '{sec_str}'")
            
            # Validate security-specific requirements
            if hasattr(cfg.security, 'security') and cfg.security.security:
                sec_str = cfg.security.security.value if isinstance(cfg.security.security, SecurityTypes) else str(cfg.security.security)
                if sec_str in ("WPA2-PSK", "WPA3-PSK", "WPA-PSK"):
                    if not cfg.security.psk or not isinstance(cfg.security.psk, str) or not cfg.security.psk.strip():
                        errors.append(f"security.psk is required for {sec_str}")
                elif sec_str in ("802.1X", "WPA2-EAP", "WPA3-EAP"):
                    if not cfg.security.identity or not isinstance(cfg.security.identity, str) or not cfg.security.identity.strip():
                        errors.append(f"security.identity is required for {sec_str}")
                    if not cfg.security.password or not isinstance(cfg.security.password, str) or not cfg.security.password.strip():
                        errors.append(f"security.password is required for {sec_str}")
        
        # Optional fields type validation
        if hasattr(cfg, 'default_route') and cfg.default_route is not None and not isinstance(cfg.default_route, bool):
            errors.append("default_route must be a boolean")
        
        if hasattr(cfg, 'autostart_app') and cfg.autostart_app is not None:
            if not isinstance(cfg.autostart_app, str) or not cfg.autostart_app.strip():
                errors.append("autostart_app must be a non-empty string if provided")
        
        if hasattr(cfg, 'mlo') and cfg.mlo is not None and not isinstance(cfg.mlo, bool):
            errors.append("mlo must be a boolean")
        
        if errors:
            error_msg = "; ".join(errors)
            return False, f"Config validation failed: {error_msg}"
        
        return True, ""

    def set_global_settings(self, settings: dict):
        self.log.info("Updating global settings: %s", settings)
        self.global_settings.update(settings)

    def parse_wpa_log(self, iface: str, timeout: int = 30):
        """
        Parse wpa_supplicant log file.
        
        Delegates to wpa.supplicant module.
        Note: Event logging is not preserved in the extracted function.
        """
        wpa_supplicant.parse_wpa_log(iface, timeout=timeout)

    def get_interfaces(self):
        """Get list of wireless interfaces using the adapter discovery module."""
        return discovery.list_interfaces()

    def _monitor_connection_async(
        self, 
        cfg: Union[NamespaceConfig, RootConfig],
        iface: str,
        namespace: Optional[str],
        timeout: int = 15
    ):
        """
        Start background connection monitor using the connection.monitor module.
        
        This method delegates to ConnectionMonitor.start_monitor() which handles
        the background monitoring, DHCP, routes, and app startup.
        """
        ConnectionMonitor.start_monitor(cfg, iface, namespace, timeout=timeout)

    def stop_connection_monitor(self, namespace: Optional[str], iface: str):
        """
        Stop a connection monitor for a specific interface/namespace.
        
        Delegates to connection.monitor module.
        """
        stop_connection_monitor(namespace, iface)

    def stop_all_connection_monitors(self):
        """
        Stop all active connection monitors. Useful for shutdown or cleanup.
        
        Delegates to connection.monitor module.
        """
        stop_all_connection_monitors()

    def activate_config(self, cfg: Union[NamespaceConfig, RootConfig]) -> NetworkSetupStatus:
        """
        Activate a network configuration. Returns NetworkSetupStatus.
        Performs comprehensive validation before any state changes.
        """
        # Validate config before any state changes
        is_valid, error_msg = self._validate_config(cfg)
        if not is_valid:
            self.log.error(f"Config validation failed, aborting activation: {error_msg}")
            log = NetworkSetupLog(selectErr=error_msg, eventLog=self.event_log)
            return NetworkSetupStatus(
                status="error",
                response=log,
                connectedNet=None,
                input=cfg.__str__(),
            )
        
        # Safe to access fields after validation
        iface = cfg.interface
        namespace = cfg.namespace if isinstance(cfg, NamespaceConfig) else None  # None = root namespace

        # Check if interface exists before proceeding
        interfaces = self.get_interfaces()
        self.log.info(f"Interfaces: {interfaces}")

        if not iface or iface not in interfaces:
            skip_msg = f"Interface '{iface}' does not exist, skipping activation for this config."
            self.log.info(skip_msg)
            log = NetworkSetupLog(selectErr=skip_msg, eventLog=self.event_log)
            # Return "provisioned" status to indicate config is valid but interface unavailable
            # This allows other interfaces in the config to still be activated
            return NetworkSetupStatus(
                status="provisioned",
                response=log,
                connectedNet=None,
                input=cfg.__str__(),
            )
            
        namespace_display = namespace if namespace else "root"
        self.log.info("Adding network on %s in namespace %s", iface, namespace_display)

        # Prepare namespace or root - this is the first state change
        if isinstance(cfg, NamespaceConfig):
            success = self._prepare_namespace(cfg)
        else:
            success = self._prepare_root(cfg)
        
        if not success:
            error_msg = "Could not complete setup (namespace/root preparation failed)."
            self.log.error(error_msg)
            log = NetworkSetupLog(selectErr=error_msg, eventLog=self.event_log)
            return NetworkSetupStatus(
                status="error",
                response=log,
                connectedNet=None,
                input=cfg.__str__(),
            )
        
        # Use display name if available, otherwise fall back to interface
        iface = cfg.iface_display_name or iface
        connected_state = False

        if cfg.security:
            # Additional validation: ensure ssid exists (should be caught by validation, but double-check)
            if not hasattr(cfg.security, 'ssid') or not cfg.security.ssid:
                error_msg = "security.ssid is required when security is provided"
                self.log.error(error_msg)
                log = NetworkSetupLog(selectErr=error_msg, eventLog=self.event_log)
                return NetworkSetupStatus(
                    status="error",
                    response=log,
                    connectedNet=None,
                    input=cfg.__str__(),
                )
            
            wpa_config.write_wpa_config(cfg, self.config_dir, self.global_settings)
            write_dhcp_config(iface, self.dhcp_dir)
            wpa_supplicant.start_or_restart_supplicant(
                iface, namespace, self.config_dir / f"{iface}.conf", self.ctrl_interface
            )
            
            # Start background connection monitor instead of blocking
            # This allows the method to return immediately with "provisioned" status
            # The monitor will handle DHCP, default route, and app startup when connection completes
            self.log.info(
                f"Started wpa_supplicant for {iface} in {namespace_display}. "
                f"Connection will be monitored in background. Returning with 'provisioned' status."
            )
            self._monitor_connection_async(cfg, iface, namespace, timeout=15)
            
            # Return immediately with "provisioned" status - connection is in progress
            connected_state = False  # Will be updated by background monitor
        else:
            # No security config, so no connection needed
            connected_state = False

        # Only attempt to set default route if explicitly requested AND connected
        # NOTE: For security configs, this is now handled by the background monitor
        # This check is only for non-security configs or immediate connection cases
        if cfg.default_route and connected_state:
            set_default_route(iface, namespace)

        # Start app if configured
        # NOTE: For security configs, app startup is now handled by background monitor
        # This is only for non-security configs
        if cfg.autostart_app and not cfg.security:
            apps.start_app_in_namespace(namespace, cfg.autostart_app, pid_dir=self.pid_dir)

        connected = None
        # For security configs with async monitoring, always return "provisioned" initially
        # The background monitor will handle connection completion
        if cfg.security:
            status_value = "provisioned"
        else:
            status_value = "connected"

        # Get mode value safely (validated, but handle enum vs string)
        mode_value = cfg.mode.value if isinstance(cfg.mode, NetworkModeEnum) else str(cfg.mode)
        
        # Only check status for non-security configs or monitor mode
        # For security configs, connection is happening asynchronously
        if mode_value != "monitor" and not cfg.security:
            status = self.get_status(iface, namespace)
            wpa: dict = status.get("wpa_status", {})
            scan: dict = status.get("connected_scan", {})

            if hasattr(cfg, 'security') and cfg.security and hasattr(cfg.security, 'ssid') and cfg.security.ssid:
                signal_val = scan.get("signal", 0)
                if signal_val is None:
                    signal_val = 0
                try:
                    signal_val = int(signal_val)
                except (TypeError, ValueError):
                    signal_val = 0
                freq_val = wpa.get("freq", 0)
                try:
                    freq_val = int(freq_val)
                except (TypeError, ValueError):
                    freq_val = 0
                connected = ScanItem(
                    ssid=cfg.security.ssid,
                    bssid=wpa.get("bssid", "unknown"),
                    key_mgmt=wpa.get("key_mgmt", "unknown"),
                    signal=signal_val,
                    freq=freq_val,
                    minrate=1000000,
                )

            wpa_state = (wpa.get("wpa_state") or "").upper()
            if wpa_state != "COMPLETED":
                status_value = "provisioned"

        log = NetworkSetupLog(selectErr="", eventLog=self.event_log)
        return NetworkSetupStatus(
            status=status_value,
            response=log,
            connectedNet=connected,
            input=cfg.__str__(),
        )
        
    def deactivate_config(self, cfg: Union[NamespaceConfig, RootConfig]):
        iface = cfg.iface_display_name or cfg.interface
        namespace = cfg.namespace if isinstance(cfg, NamespaceConfig) else None  # None = root namespace
        
        # Stop any active connection monitor for this config
        self.stop_connection_monitor(namespace, iface)
        
        # Check if interface actually exists before trying to deactivate
        interfaces = self.get_interfaces()
        if iface not in interfaces:
            self.log.info(f"Interface {iface} does not exist, skipping deactivation")
            return
        
        if cfg.autostart_app:
            apps.stop_app_in_namespace(namespace, pid_dir=self.pid_dir)
        if cfg.security:
            try:
                self.remove_network(iface, namespace)
            except RunCommandError as e:
                namespace_display = namespace if namespace else "root"
                self.log.warning(f"Failed to remove network {iface} in namespace {namespace_display}: {e} (non-critical)")

        self.revert_to_root(cfg)
            

    def remove_network(self, iface: str, namespace: Optional[str]):
        namespace_display = namespace if namespace else "root"
        self.log.info("Removing network %s from namespace %s", iface, namespace_display)

        # Fixed: Enhanced cleanup for wlan<index>.conf files
        config_files_to_remove = [
            self.config_dir / f"{iface}.conf",
            self.dhcp_dir / f"{iface}.cfg",
        ]
        
        # Add wlan<index>.conf if interface follows pattern
        if iface.startswith("wlan") and len(iface) > 4:
            try:
                index = iface[4:]
                if index.isdigit():
                    config_files_to_remove.append(self.config_dir / f"wlan{index}.conf")
                    config_files_to_remove.append(self.dhcp_dir / f"wlan{index}.cfg")
            except:
                pass
        
        for config_file in config_files_to_remove:
            self._safe_unlink(config_file)

        # self._ns_exec(["pkill", "-f", f"wpa_supplicant.*-i{iface}"], namespace)
        self._ns_exec(["pkill", "-f", "wpa_supplicant"], namespace)
        self._ns_exec(["rm", "-f", f"{self.ctrl_interface}/{iface}"], namespace)
        self._ns_exec(["dhclient", "-r", iface], namespace)

    def revert_to_root(self, cfg: Union[NamespaceConfig, RootConfig, None] = None, delete_namespace: bool = True):
        # If no cfg provided: scan all namespaces and move all interfaces/PHYs back to root
        if cfg is None:
            try:
                namespace_names = ns_namespace.list_namespaces()
            except Exception as e:
                self.log.warning(f"Failed to list namespaces: {e}")
                namespace_names = []

            for ns_name in namespace_names:
                try:
                    self.log.info(f"Moving interfaces from namespace {ns_name} back to root")
                    # Stop any wpa_supplicant processes in this namespace to avoid hangers
                    try:
                        self._ns_exec(["pkill", "-f", "wpa_supplicant"], ns_name)
                    except RunCommandError:
                        pass
                    # List interfaces in the namespace using namespace interfaces module
                    iface_names = ns_interfaces.get_interfaces_in_namespace(ns_name, include_loopback=False)

                    for name in iface_names:
                        if name.startswith("lo"):
                            continue
                        if name.startswith("wlan"):
                            # Determine phy for this interface and move phy to root
                            try:
                                info_output = self._ns_exec(["iw", "dev", name, "info"], ns_name).stdout
                                # look for 'wiphy N'
                                phy_num = None
                                for info_line in info_output.splitlines():
                                    info_line = info_line.strip()
                                    if info_line.startswith("wiphy "):
                                        try:
                                            phy_num = int(info_line.split()[1])
                                        except Exception:
                                            phy_num = None
                                        break
                                # Best-effort cleanup of control interface socket
                                try:
                                    self._ns_exec(["rm", "-f", f"{self.ctrl_interface}/{name}"], ns_name)
                                except RunCommandError:
                                    pass
                                if phy_num is not None:
                                    phy_name = f"phy{phy_num}"
                                    phy.move_phy_to_root(phy_name, ns_name)
                                    self.log.info(f"Moved {phy_name} from namespace {ns_name} back to root")
                                else:
                                    # Fallback: try moving link if phy not parsed
                                    ns_interfaces.move_interface_to_root(name, ns_name)
                                    self.log.info(f"Moved {name} from namespace {ns_name} back to root (link move)")
                            except RunCommandError as e:
                                self.log.warning(f"Failed moving wireless interface {name} from {ns_name}: {e}")
                        else:
                            # Try generic link move for non-wlan interfaces (e.g., eth*)
                            try:
                                # Best-effort cleanup of control interface socket (if any naming overlap)
                                try:
                                    self._ns_exec(["rm", "-f", f"{self.ctrl_interface}/{name}"], ns_name)
                                except RunCommandError:
                                    pass
                                ns_interfaces.move_interface_to_root(name, ns_name)
                                self.log.info(f"Moved {name} from namespace {ns_name} back to root")
                            except RunCommandError as e:
                                self.log.warning(f"Failed moving interface {name} from {ns_name}: {e}")

                    if delete_namespace:
                        # Stop any app running in this namespace before deletion
                        self.stop_app_in_namespace(ns_name)
                        try:
                            ns_namespace.delete_namespace(ns_name, raise_on_fail=False)
                            self.log.info(f"Deleted namespace {ns_name}")
                        except Exception as e:
                            self.log.warning(f"Could not delete namespace {ns_name}: {e}")
                except Exception as e:
                    self.log.warning(f"Issue reverting namespace {ns_name} to root: {e}")
            return

        iface_before = cfg.iface_display_name or cfg.interface
        iface = cfg.interface
        namespace = cfg.namespace if isinstance(cfg, NamespaceConfig) else None  # None = root namespace
        namespace_display = namespace if namespace else "root"
        
        # Check if interface actually exists before attempting revert
        interfaces = self.get_interfaces()
        if iface not in interfaces:
            self.log.info(f"Interface {iface} does not exist, skipping revert")
            return
        
        self.log.info(
            f"Reverting {iface_before} and {cfg.phy} from namespace {namespace_display} to root namespace."
        )

        # For root namespace (None), we don't need to move things "back" - they're already there
        if namespace is None:
            self.log.debug(f"Config is already in root namespace, minimal cleanup needed")
            # Just clean up any processes/configs, but don't try to move things
            try:
                self._ns_exec(["pkill", "-f", f"wpa_supplicant.*-i{iface_before}"], namespace)
            except RunCommandError:
                pass
            try:
                self._ns_exec(["rm", "-f", f"{self.ctrl_interface}/{iface_before}"], namespace)
            except RunCommandError:
                pass
            try:
                self._ns_exec(["dhclient", "-r", iface_before], namespace)
            except RunCommandError:
                pass
            return  # Don't try to delete "root" namespace or move things that are already in root

        # For actual namespaces, do the full revert
        # Ensure any wpa_supplicant and dhclient tied to this interface are stopped in the namespace
        try:
            self._ns_exec(["pkill", "-f", f"wpa_supplicant.*-i{iface_before}"], namespace)
        except RunCommandError:
            pass
        try:
            self._ns_exec(["rm", "-f", f"{self.ctrl_interface}/{iface_before}"], namespace)
        except RunCommandError:
            pass
        try:
            self._ns_exec(["dhclient", "-r", iface_before], namespace)
        except RunCommandError:
            pass

        # Try to delete the interface in the namespace if it exists
        try:
            interface.delete_interface(iface_before, namespace=namespace)
            self.log.info(f"Deleted {iface_before} in namespace {namespace_display}.")
        except RunCommandError as e:
            if "No such device" in str(e):
                self.log.debug(f"No {iface_before} found to delete in {namespace_display}.")
            else:
                self.log.warning(f"Failed to delete {iface_before} in {namespace_display}: {e}")

        # Check if PHY exists before trying to move it
        try:
            # First check if PHY exists in the system
            phys_in_root = phy.list_phys(namespace=None)
            if cfg.phy not in phys_in_root:
                # Check if PHY is in the namespace
                phys_in_ns = phy.list_phys(namespace=namespace)
                if cfg.phy in phys_in_ns:
                    phy.move_phy_to_root(cfg.phy, namespace)
                    self.log.info(f"Moved {cfg.phy} from namespace {namespace_display} back to root.")
                else:
                    self.log.debug(
                        f"PHY {cfg.phy} not found in {namespace_display}, assuming it's already in root."
                    )
            else:
                self.log.debug(f"PHY {cfg.phy} already in root, skipping move")
        except RunCommandError as e:
            self.log.warning(f"Could not check or move {cfg.phy} from {namespace_display}: {e}")

        # Only try to create interface if PHY exists
        try:
            phys_in_root = phy.list_phys(namespace=None)
            if cfg.phy in phys_in_root:
                interface.create_interface(cfg.phy, iface, interface_type="managed", namespace=None)
                self.log.info(f"Created {iface} in root namespace.")
            else:
                self.log.debug(f"PHY {cfg.phy} does not exist, cannot create {iface}")
        except RunCommandError as e:
            self.log.warning(f"Could not create {iface} in root: {e}")

        # Only try to bring up interface if it exists
        try:
            if iface in self.get_interfaces():
                interface.bring_interface_up(iface, namespace=None)
                self.log.info(f"Brought {iface} up in root namespace.")
            else:
                self.log.debug(f"Interface {iface} does not exist, cannot bring it up")
        except RunCommandError as e:
            self.log.warning(f"Could not bring up {iface} in root: {e}")

        # Optionally delete the namespace (None = root namespace, which is not a real namespace)
        if delete_namespace and namespace is not None:
            # Stop any app running in this namespace before deletion
            self.stop_app_in_namespace(namespace)
            # Check if namespace actually exists before trying to delete
            try:
                namespace_names = ns_namespace.list_namespaces()
                if namespace in namespace_names:
                    try:
                        ns_namespace.delete_namespace(namespace, raise_on_fail=False)
                        self.log.info(f"Deleted namespace {namespace}.")
                    except Exception as e:
                        self.log.warning(f"Could not delete namespace {namespace}: {e}")
                else:
                    self.log.debug(f"Namespace {namespace} does not exist, skipping deletion")
            except Exception as e:
                self.log.warning(f"Could not check namespace list before deletion: {e}")

    def start_app_in_namespace(self, namespace: Optional[str], app_id):
        """
        Start an application in a namespace or root namespace.
        
        Delegates to namespaces.apps module.
        """
        apps.start_app_in_namespace(namespace, app_id, pid_dir=self.pid_dir)

    def stop_app_in_namespace(self, namespace: Optional[str]):
        """
        Stop an application running in a namespace or root namespace.
        
        Delegates to namespaces.apps module.
        """
        apps.stop_app_in_namespace(namespace, pid_dir=self.pid_dir)

    def get_status(self, iface: str, namespace: Optional[str]) -> dict:
        """
        Get network status for an interface.
        
        Delegates to wpa.status module.
        """
        return wpa_status.get_wpa_status(iface, namespace)
    
    def _prepare_root(self, cfg: RootConfig):
        """
        Prepare root namespace for network configuration using the new modules.
        
        This method now delegates to the extracted adapter and interface modules.
        """
        try:
            iface = cfg.interface

            # Clean up any stale interface using interface module
            try:
                interface.delete_interface(iface, namespace=None)
            except RunCommandError as e:
                if "No such device" in str(e):
                    self.log.info(f"No {iface} to delete in root. ignoring.")
                else:
                    raise

            phy = cfg.phy


            # Check if phy is already in root; if not, attach it
            result = self._run(["iw", "phy"], no_output=True)
            if phy not in result.stdout:
                self.log.info(f"Attaching {phy} to root namespace")
                try:
                    self._run(["sudo", "iw", "phy", phy, "set", "netns", "1"])
                except RunCommandError as e:
                    self.log.info(f"{phy} does not exist. skipping this config.")
                    return False
            else:
                self.log.info(f"{phy} already in root namespace")

            # Create the wlan interface
            iface_name = cfg.iface_display_name or iface
            # Get mode value safely (validated, but handle enum vs string)
            mode_value = cfg.mode.value if isinstance(cfg.mode, NetworkModeEnum) else str(cfg.mode)
            try:
                self.log.info(f"adding {iface} as {iface_name} in root")
                self._run(
                    ["iw", "phy", phy, "interface", "add", iface_name, "type", mode_value],
                    
                )
            except:
                self.log.info(f"{iface} already exists")
                
            

            # Bring up the new interface
            self.log.info("Bringing up %s in root", iface_name)
            self._run(["ip", "link", "set", iface_name, "up"])
            
            return True

        except RunCommandError as e:
            self.log.error(f"Root setup failed for {iface}: {e}")
            raise

    def _prepare_namespace(self, cfg: NamespaceConfig):
        namespace = cfg.namespace
        iface = cfg.interface
        if not namespace:
            return

        try:
            # Ensure namespace exists using namespace module
            if not ns_namespace.namespace_exists(namespace):
                self.log.info("Creating namespace %s", namespace)
                ns_namespace.create_namespace(namespace)
            else:
                self.log.info("Namespace %s already exists", namespace)

            # Clean up any stale interface using interface module
            try:
                interface.delete_interface(iface, namespace=namespace)
            except RunCommandError as e:
                if "No such device" in str(e):
                    self.log.info(f"No {iface} to delete in {namespace}. ignoring.")
                else:
                    raise

            phy_name = cfg.phy

            # Check if PHY is already in namespace, move it back to root first if needed
            phys_in_ns = phy.list_phys(namespace=namespace)
            if phy_name in phys_in_ns:
                self.log.info("Moving %s back to root from namespace %s", phy_name, namespace)
                phy.move_phy_to_root(phy_name, namespace)
            else:
                self.log.info(
                    f"{phy_name} not found in {namespace}. assume it's in root already."
                )

            # Attach PHY to target namespace using phy module
            self.log.info(f"Attaching {phy_name} to namespace {namespace}")
            try:
                phy.move_phy_to_namespace(phy_name, namespace)
            except RunCommandError as e:
                self.log.info(f"{phy_name} does not exist. skipping this config.")
                return False

            # Create the wlan interface
            iface_name = cfg.iface_display_name or iface
            # Get mode value safely (validated, but handle enum vs string)
            mode_value = cfg.mode.value if isinstance(cfg.mode, NetworkModeEnum) else str(cfg.mode)
            try:
                self.log.info(f"adding {iface} as {iface_name} in namespace {namespace}")
                interface.create_interface(phy_name, iface_name, interface_type=mode_value, namespace=namespace)
            except RunCommandError:
                self.log.info(f"{iface} already exists")
                
            

            # Bring up the interface using interface module
            self.log.info("Bringing up %s in namespace %s", iface_name, namespace)
            interface.bring_interface_up(iface_name, namespace=namespace)
            return True

        except RunCommandError as e:
            self.log.error("Namespace setup failed for %s: %s", iface, e)
            raise

   


    def _run(self, cmd, no_output=False):
        self.log.info(f"Running: {' '.join(cmd)}")
        try:
            output = run_command(cmd)
            if no_output:
                return output
            self.log.info(f"stdout: {output.stdout}")
            self.log.info(f"stderr: {output.stderr}")
            self.log.info(f"return_code: {output.return_code}")
            if output.return_code != 0:
                raise RunCommandError(output.stderr.decode(), output.return_code)
            return output
        except Exception as e:
            self.log.error(f"Command failed: {' '.join(cmd)}\nError: {e}")
            raise

    def _ns_exec(self, cmd, namespace: Optional[str], no_output=False):
        """
        Execute a command in a namespace or root namespace.
        
        This method wraps the namespace execution utility, adding service-level
        logging. For direct namespace execution, use wlanpi_core.utils.namespace_execution.ns_exec.
        """
        # Use the extracted utility, but wrap with service-level logging
        try:
            result = ns_exec(cmd, namespace=namespace, no_output=no_output, raise_on_fail=True)
            if not no_output:
                self.log.info(f"Command succeeded in namespace '{namespace or 'root'}': {' '.join(cmd)}")
            return result
        except RunCommandError as e:
            self.log.error(f"Command failed in namespace '{namespace or 'root'}': {' '.join(cmd)} - {e}")
            raise

    def _safe_unlink(self, path: Path):
        if path.exists():
            path.unlink()

    def _log_event(self, event: str, timestamp: str = None):
        """
        Log a network event to the event log.
        
        Args:
            event: Event message
            timestamp: Optional timestamp (defaults to current time)
        """
        from datetime import datetime
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        self.event_log.append(NetworkEvent(event=event, time=timestamp))

    def kill_all_supplicants(self):
        """
        Stop any running wpa_supplicant processes across namespaces.

        Delegates to wpa.supplicant module.
        """
        wpa_supplicant.kill_all_supplicants()
