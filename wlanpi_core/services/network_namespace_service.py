import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

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
        self.event_log: List[NetworkEvent] = []
        
        # Connection monitoring for async network connection
        self._connection_monitors: Dict[str, threading.Thread] = {}
        self._monitor_stop_flags: Dict[str, threading.Event] = {}
        self._monitor_lock = threading.Lock()

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
        start_time = time.time()

        with open(f"/tmp/wpa-{iface}.log", "r") as f:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                    if time.time() - start_time > timeout:
                        raise TimeoutError("Timeout waiting for connection to complete")
                    continue

                line = line.strip()

                # Extract timestamp if present
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[0].replace(".", "", 1).isdigit():
                    epoch = float(parts[0])
                    log_msg = parts[1].strip()
                    ts = datetime.fromtimestamp(epoch).isoformat()
                else:
                    epoch = None
                    log_msg = line
                    ts = datetime.now().isoformat()

                self._log_event(log_msg, timestamp=ts)

                if "CTRL-EVENT-CONNECTED" in line and "completed" in line:
                    break

    def get_interfaces(self):
        output = self._run([IW_FILE, "dev"])
        interfaces = []
        current_iface = None
        if not output:
            return interfaces

        for line in output.stdout.splitlines():
            if line.strip().startswith("Interface"):
                current_iface = line.strip().split()[1]
                interfaces.append(current_iface)
        
        return interfaces

    def _monitor_connection_async(
        self, 
        cfg: Union[NamespaceConfig, RootConfig],
        iface: str,
        namespace: Optional[str],
        timeout: int = 15
    ):
        """
        Background thread to monitor network connection and start DHCP/apps when ready.
        This allows activate_config to return immediately without blocking.
        """
        namespace_display = namespace if namespace else "root"
        monitor_key = f"{namespace_display}:{iface}"
        
        def monitor_loop():
            self.log.info(f"[ConnectionMonitor] Starting connection monitor for {iface} in {namespace_display} (timeout={timeout}s)")
            start = time.time()
            poll_interval = 1
            saw_only_scanning = True
            last_state = None
            connected_state = False
            poll_count = 0
            
            stop_event = self._monitor_stop_flags.get(monitor_key)
            if not stop_event:
                self.log.error(f"[ConnectionMonitor] No stop event found for {monitor_key}, monitor cannot start")
                return
            
            self.log.info(f"[ConnectionMonitor] Monitor loop started for {iface} in {namespace_display}, beginning status checks...")
            
            while time.time() - start < timeout:
                # Check if we should stop
                if stop_event.is_set():
                    self.log.info(f"[ConnectionMonitor] Connection monitor for {iface} in {namespace_display} stopped by stop event")
                    return
                
                try:
                    status = self.get_status(iface, namespace)
                    wpa: dict = status.get("wpa_status", {})
                    wpa_state = (wpa.get("wpa_state") or "").upper()
                    last_state = wpa_state
                    poll_count += 1
                    
                    # Log status every 3 polls (every ~3 seconds) to show monitor is active
                    if poll_count % 3 == 0:
                        elapsed = int(time.time() - start)
                        self.log.info(
                            f"[ConnectionMonitor] Status check #{poll_count} for {iface} in {namespace_display}: "
                            f"wpa_state={wpa_state}, elapsed={elapsed}s/{timeout}s"
                        )
                    
                    if wpa_state == "COMPLETED":
                        connected_state = True
                        elapsed = int(time.time() - start)
                        self.log.info(
                            f"[ConnectionMonitor] Connection completed for {iface} in {namespace_display} "
                            f"after {elapsed}s ({poll_count} status checks)"
                        )
                        break
                        
                    if wpa_state != "SCANNING":
                        saw_only_scanning = False
                        
                    time.sleep(poll_interval)
                except Exception as e:
                    self.log.warning(f"[ConnectionMonitor] Error checking connection status for {iface}: {e}", exc_info=True)
                    time.sleep(poll_interval)
            
            # Clean up monitor tracking
            with self._monitor_lock:
                self._connection_monitors.pop(monitor_key, None)
                self._monitor_stop_flags.pop(monitor_key, None)
            
            if connected_state:
                # Start DHCP after connection
                try:
                    self.log.info(f"[ConnectionMonitor] Starting DHCP for {iface} in {namespace_display} after connection")
                    self._restart_dhcp_with_timeout(iface, namespace)
                    
                    # Parse WPA log for events
                    try:
                        self.parse_wpa_log(iface)
                    except TimeoutError:
                        self.log.warning(f"[ConnectionMonitor] Timeout parsing WPA log for {iface}")
                    
                    # Set default route if requested
                    if cfg.default_route:
                        self.log.info(f"[ConnectionMonitor] Setting default route for {iface} in {namespace_display}")
                        self._set_default_route(iface, namespace)
                    
                    # Start app if configured
                    if cfg.autostart_app:
                        self.log.info(f"[ConnectionMonitor] Starting autostart app '{cfg.autostart_app}' for {iface} in {namespace_display}")
                        self.start_app_in_namespace(namespace, cfg.autostart_app)
                    
                    self.log.info(f"[ConnectionMonitor] Connection setup complete for {iface} in {namespace_display}")
                except Exception as e:
                    self.log.error(f"[ConnectionMonitor] Error completing connection setup for {iface}: {e}", exc_info=True)
            else:
                # Not connected within timeout
                elapsed = int(time.time() - start)
                self.log.info(
                    f"[ConnectionMonitor] Did not reach connected state within {timeout}s for {iface} in {namespace_display} "
                    f"(last_state={last_state}, elapsed={elapsed}s, checks={poll_count}). "
                    f"Configuration remains active for future connection."
                )
        
        # Create and start monitor thread
        self.log.info(
            f"[ConnectionMonitor] Creating monitor thread for {iface} in {namespace_display} "
            f"(monitor_key={monitor_key})"
        )
        stop_event = threading.Event()
        monitor_thread = threading.Thread(
            target=monitor_loop,
            name=f"ConnectionMonitor-{monitor_key}",
            daemon=True
        )
        
        with self._monitor_lock:
            self._connection_monitors[monitor_key] = monitor_thread
            self._monitor_stop_flags[monitor_key] = stop_event
        
        try:
            monitor_thread.start()
            self.log.info(
                f"[ConnectionMonitor] Connection monitor thread started successfully for {iface} in {namespace_display} "
                f"(thread={monitor_thread.name}, daemon={monitor_thread.daemon}, alive={monitor_thread.is_alive()})"
            )
        except Exception as e:
            self.log.error(
                f"[ConnectionMonitor] Failed to start monitor thread for {iface} in {namespace_display}: {e}",
                exc_info=True
            )
            # Clean up on failure
            with self._monitor_lock:
                self._connection_monitors.pop(monitor_key, None)
                self._monitor_stop_flags.pop(monitor_key, None)

    def stop_connection_monitor(self, namespace: Optional[str], iface: str):
        """
        Stop a connection monitor for a specific interface/namespace.
        """
        namespace_display = namespace if namespace else "root"
        monitor_key = f"{namespace_display}:{iface}"
        
        with self._monitor_lock:
            stop_event = self._monitor_stop_flags.get(monitor_key)
            monitor_thread = self._connection_monitors.get(monitor_key)
            
            if stop_event:
                stop_event.set()
            
            if monitor_thread and monitor_thread.is_alive():
                monitor_thread.join(timeout=2.0)
            
            self._connection_monitors.pop(monitor_key, None)
            self._monitor_stop_flags.pop(monitor_key, None)

    def stop_all_connection_monitors(self):
        """
        Stop all active connection monitors. Useful for shutdown or cleanup.
        """
        with self._monitor_lock:
            # Signal all monitors to stop
            for stop_event in self._monitor_stop_flags.values():
                stop_event.set()
            
            # Wait for all threads to finish (with timeout)
            for monitor_key, monitor_thread in list(self._connection_monitors.items()):
                if monitor_thread.is_alive():
                    monitor_thread.join(timeout=2.0)
                    if monitor_thread.is_alive():
                        self.log.warning(f"Connection monitor {monitor_key} did not stop within timeout")
            
            self._connection_monitors.clear()
            self._monitor_stop_flags.clear()
        
        self.log.info("All connection monitors stopped")

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
<<<<<<< HEAD
        
        # Handle security configuration
=======
>>>>>>> upstream/dev
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
            
            self._write_config(cfg)
            self._write_dhcp_config(iface)
            self._start_or_restart_supplicant(iface, namespace)
            
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
            self._set_default_route(iface, namespace)

        # Start app if configured
        # NOTE: For security configs, app startup is now handled by background monitor
        # This is only for non-security configs
        if cfg.autostart_app and not cfg.security:
            self.start_app_in_namespace(namespace, cfg.autostart_app)

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
            self.stop_app_in_namespace(namespace)
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
                ns_list_output = self._run(["ip", "netns", "list"]).stdout
                namespace_names = [line.split()[0] for line in ns_list_output.splitlines() if line.strip()]
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
                    # List interfaces in the namespace
                    links_output = self._ns_exec(["ip", "-o", "link", "show"], ns_name).stdout
                    iface_names = []
                    for line in links_output.splitlines():
                        # format: '1: lo: <...> ...'
                        parts = line.split(":", 2)
                        if len(parts) >= 2:
                            name = parts[1].strip()
                            iface_names.append(name)

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
                                    self._ns_exec(["iw", "phy", f"phy{phy_num}", "set", "netns", "1"], ns_name)
                                    self.log.info(f"Moved phy{phy_num} from namespace {ns_name} back to root")
                                else:
                                    # Fallback: try moving link if phy not parsed
                                    self._ns_exec(["ip", "link", "set", name, "netns", "1"], ns_name)
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
                                self._ns_exec(["ip", "link", "set", name, "netns", "1"], ns_name)
                                self.log.info(f"Moved {name} from namespace {ns_name} back to root")
                            except RunCommandError as e:
                                self.log.warning(f"Failed moving interface {name} from {ns_name}: {e}")

                    if delete_namespace:
<<<<<<< HEAD
                        # Stop any app running in this namespace before deletion
                        self.stop_app_in_namespace(ns_name)
=======
>>>>>>> upstream/dev
                        try:
                            self._run(["ip", "netns", "delete", ns_name])
                            self.log.info(f"Deleted namespace {ns_name}")
                        except RunCommandError as e:
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
            self._ns_exec(["iw", "dev", iface_before, "del"], namespace)
            self.log.info(f"Deleted {iface_before} in namespace {namespace_display}.")
        except RunCommandError as e:
            if "No such device" in str(e):
                self.log.debug(f"No {iface_before} found to delete in {namespace_display}.")
            else:
                self.log.warning(f"Failed to delete {iface_before} in {namespace_display}: {e}")

        # Check if PHY exists before trying to move it
        try:
            # First check if PHY exists in the system
            phy_list_output = self._run(["iw", "phy"], no_output=True).stdout
            if cfg.phy not in phy_list_output:
                self.log.debug(f"PHY {cfg.phy} does not exist, skipping PHY move")
            else:
                # Check if PHY is in the namespace
                phy_result = self._ns_exec(
                    ["iw", "phy"], namespace, no_output=True
                )
                if cfg.phy in phy_result.stdout:
                    self._ns_exec(
                        [
                            "iw",
                            "phy",
                            cfg.phy,
                            "set",
                            "netns",
                            "1",
                        ], namespace
                    )
                    self.log.info(f"Moved {cfg.phy} from namespace {namespace_display} back to root.")
                else:
                    self.log.debug(
                        f"PHY {cfg.phy} not found in {namespace_display}, assuming it's already in root."
                    )
        except RunCommandError as e:
            self.log.warning(f"Could not check or move {cfg.phy} from {namespace_display}: {e}")

        # Only try to create interface if PHY exists
        try:
            phy_list_output = self._run(["iw", "phy"], no_output=True).stdout
            if cfg.phy in phy_list_output:
                self._run(
                    ["iw", "phy", cfg.phy, "interface", "add", iface, "type", "managed"]
                )
                self.log.info(f"Created {iface} in root namespace.")
            else:
                self.log.debug(f"PHY {cfg.phy} does not exist, cannot create {iface}")
        except RunCommandError as e:
            self.log.warning(f"Could not create {iface} in root: {e}")

        # Only try to bring up interface if it exists
        try:
            if iface in self.get_interfaces():
                self._run(["ip", "link", "set", iface, "up"])
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
                ns_list_output = self._run(["ip", "netns", "list"]).stdout
                namespace_names = [line.split()[0] for line in ns_list_output.splitlines() if line.strip()]
                if namespace in namespace_names:
                    try:
                        self._run(["ip", "netns", "delete", namespace])
                        self.log.info(f"Deleted namespace {namespace}.")
                    except RunCommandError as e:
                        if "No such file or directory" in str(e):
                            self.log.info(f"Namespace {namespace} already deleted.")
                        else:
                            self.log.warning(f"Could not delete namespace {namespace}: {e}")
                else:
                    self.log.debug(f"Namespace {namespace} does not exist, skipping deletion")
            except Exception as e:
                self.log.warning(f"Could not check namespace list before deletion: {e}")

    def start_app_in_namespace(self, namespace: Optional[str], app_id):
        apps_file = Path(APPS_FILE)
        if not apps_file.exists():
            apps_file.touch()
        try:
            with apps_file.open("r") as f:
                apps = json.load(f)
        except json.JSONDecodeError as e:
            self.log.error(f"Failed to parse apps file {APPS_FILE}: {e}")
            return
        if app_id not in apps:
            self.log.error(f"App ID {app_id} not found in apps file.")
            return
        app_command = apps[app_id]
        
        namespace_display = namespace if namespace else "root"
        self.log.info(f"Starting app '{app_id}' in namespace '{namespace_display}' with command: {app_command}")

        if namespace is None:  # None = root namespace
            cmd = app_command.split()
            pid_file = self.pid_dir / "root.pid"
        else:
            cmd = ["ip", "netns", "exec", namespace] + app_command.split()
            pid_file = self.pid_dir / f"{namespace}.pid"
        
        # Log the full command being executed
        self.log.info(f"Executing command: {' '.join(cmd)}")
        self.log.info(f"App log file will be written to: /tmp/{app_id}.log")
            
        # Clear/create log file
        log_file_path = Path(f"/tmp/{app_id}.log")
        with log_file_path.open("w"):
            pass
        
        with log_file_path.open("w") as log_file:
            proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
        
        # Store both PID and app_command for reliable cleanup
        pid_data = {"pid": proc.pid, "app_id": app_id, "app_command": app_command}
        pid_file.write_text(json.dumps(pid_data))
        
        self.log.info(f"Launched app '{app_id}' in namespace '{namespace_display}' with PID {proc.pid}")
        
        # Wait a moment for process to start
        time.sleep(0.5)
        
        # Verify process is running
        try:
            # Check if process still exists (poll() returns None if running, returncode if finished)
            if proc.poll() is None:
                self.log.info(f"Process {proc.pid} is running (confirmed via poll())")
            else:
                returncode = proc.poll()
                self.log.warning(f"Process {proc.pid} exited immediately with return code {returncode}")
                # Try to read some log output for diagnosis
                if log_file_path.exists():
                    try:
                        log_content = log_file_path.read_text()[:500]  # First 500 chars
                        if log_content:
                            self.log.warning(f"Process log output: {log_content}")
                    except Exception:
                        pass
                return
        except Exception as e:
            self.log.warning(f"Could not verify process status: {e}")
        
        # For namespaced apps, verify it's visible in the namespace
        if namespace is not None:
            try:
                ns_pids_result = self._run(["ip", "netns", "pids", namespace], no_output=True)
                ns_pids = [int(pid) for pid in ns_pids_result.stdout.strip().split() if pid.strip().isdigit()]
                if proc.pid in ns_pids:
                    self.log.info(f"Process {proc.pid} confirmed visible in namespace '{namespace}' (found in namespace PIDs)")
                else:
                    # Note: The PID might be the ip wrapper, not the actual app process
                    # Check for child processes or processes matching the command
                    self.log.info(f"Process {proc.pid} not directly in namespace PIDs list (may be wrapper process). Namespace PIDs: {ns_pids}")
                    # Try to find the actual app process in the namespace
                    try:
                        # Use ps to find processes matching the app command in the namespace
                        cmd_parts = app_command.split()
                        if cmd_parts:
                            base_cmd = cmd_parts[0]
                            ps_result = self._ns_exec(["ps", "aux"], namespace, no_output=True)
                            matching_lines = [line for line in ps_result.stdout.splitlines() if base_cmd in line]
                            if matching_lines:
                                self.log.info(f"Found {len(matching_lines)} process(es) matching '{base_cmd}' in namespace '{namespace}'")
                                for line in matching_lines[:3]:  # Log first 3 matches
                                    self.log.debug(f"  {line.strip()}")
                    except Exception as e:
                        self.log.debug(f"Could not check for app process in namespace: {e}")
            except Exception as e:
                self.log.warning(f"Could not verify process in namespace '{namespace}': {e}")
        
        # Try to check network interface bindings
        try:
            # Use 'ss' or 'netstat' to see what interfaces the process is bound to
            # First try 'ss' (more modern, better for namespaces)
            try:
                # Use 'ss' to check network bindings (works in both root and namespaced contexts)
                ss_cmd = ["ss", "-tulpn"]
                ss_result = self._ns_exec(ss_cmd, namespace, no_output=True)
                # Look for lines containing our PID (though this might be the wrapper PID)
                pid_str = str(proc.pid)
                bindings = [line for line in ss_result.stdout.splitlines() if pid_str in line]
                
                if bindings:
                    self.log.info(f"Process {proc.pid} has {len(bindings)} network binding(s):")
                    for binding in bindings[:5]:  # Log first 5 bindings
                        # Extract interface/address info if available
                        self.log.info(f"  {binding.strip()}")
                else:
                    self.log.info(f"No network bindings found for PID {proc.pid} yet (process may not have bound to interfaces yet)")
            except Exception:
                # Fallback to checking /proc/net or using netstat if ss fails
                try:
                    # List interfaces available in the namespace
                    iface_cmd = ["ip", "-o", "link", "show"]
                    iface_result = self._ns_exec(iface_cmd, namespace, no_output=True)
                    interfaces = []
                    for line in iface_result.stdout.splitlines():
                        parts = line.split(":", 2)
                        if len(parts) >= 2:
                            iface_name = parts[1].strip()
                            if not iface_name.startswith("lo"):
                                interfaces.append(iface_name)
                    if interfaces:
                        self.log.info(f"Network interfaces available in namespace '{namespace_display}': {', '.join(interfaces)}")
                        self.log.info(f"App '{app_id}' may bind to one of these interfaces")
                    else:
                        self.log.warning(f"No network interfaces found in namespace '{namespace_display}' (except loopback)")
                except Exception as e:
                    self.log.debug(f"Could not list namespace interfaces: {e}")
        except Exception as e:
            self.log.debug(f"Could not check network bindings for process: {e}")
        
        self.log.info(f"App '{app_id}' startup verification complete. Monitor logs at /tmp/{app_id}.log")

    def stop_app_in_namespace(self, namespace: Optional[str]):
        # Handle PID file naming for root namespace
        if namespace is None:
            pid_file = self.pid_dir / "root.pid"
            namespace_display = "root"
        else:
            pid_file = self.pid_dir / f"{namespace}.pid"
            namespace_display = namespace
            
        if pid_file.exists():
            try:
                pid_data_str = pid_file.read_text().strip()
                try:
                    # Try to parse as JSON (new format with app_command)
                    pid_data = json.loads(pid_data_str)
                    pid = pid_data.get("pid")
                    app_command = pid_data.get("app_command", "")
                    app_id = pid_data.get("app_id", "")
                except (json.JSONDecodeError, ValueError, TypeError):
                    # Fall back to old format (just PID number)
                    pid = int(pid_data_str)
                    app_command = ""
                    app_id = ""
                
                if namespace is None:
                    # Root namespace: use simpler approach (no namespace isolation)
                    try:
                        if pid:
                            self._run(["kill", str(pid)])
                            self.log.info(f"Stopped app in {namespace_display} with PID {pid}")
                        elif app_command:
                            # Extract the base command (first part) for matching
                            cmd_parts = app_command.split()
                            if cmd_parts:
                                base_cmd = cmd_parts[0]
                                self._run(["pkill", "-f", base_cmd])
                                self.log.info(f"Stopped app in {namespace_display} using pkill for {base_cmd}")
                    except RunCommandError as e:
                        self.log.warning(f"Failed to kill app in {namespace_display}: {e}")
                else:
                    # Namespace operations: use ip netns commands for safety
                    
                    # Step 1: Verify namespace exists
                    try:
                        ns_list = self._run(["ip", "netns", "list"], no_output=True)
                        if namespace not in ns_list.stdout:
                            self.log.warning(f"Namespace {namespace} does not exist, skipping app stop")
                            return
                    except Exception as e:
                        self.log.warning(f"Could not verify namespace exists: {e}")
                        return
                    
                    # Step 2: Verify PID from file is actually in this namespace
                    verified_pid = None
                    if pid:
                        try:
                            identify_result = self._run(["ip", "netns", "identify", str(pid)], no_output=True)
                            if namespace in identify_result.stdout:
                                verified_pid = pid
                                self.log.info(f"PID {pid} confirmed in namespace {namespace}")
                            else:
                                self.log.warning(
                                    f"PID {pid} is not in namespace {namespace} "
                                    f"(found in: {identify_result.stdout.strip() or 'unknown'}), "
                                    f"will search namespace for matching processes"
                                )
                        except RunCommandError as e:
                            # Process may not exist or identify may fail, continue with pids list method
                            self.log.debug(f"Could not identify namespace for PID {pid}: {e}")
                    
                    # Step 3: Get all PIDs in the namespace
                    try:
                        pids_result = self._run(["ip", "netns", "pids", namespace], no_output=True)
                        ns_pids = [int(p) for p in pids_result.stdout.strip().split() if p.strip().isdigit()]
                        
                        if not ns_pids:
                            self.log.info(f"No processes found in namespace {namespace}")
                            return
                        
                        self.log.debug(f"Found {len(ns_pids)} process(es) in namespace {namespace}")
                        
                        # Step 4: Find matching PIDs by checking command lines
                        matching_pids = []
                        if app_command:
                            cmd_parts = app_command.split()
                            base_cmd = cmd_parts[0] if cmd_parts else ""
                            
                            # Also check if verified_pid is in the namespace PIDs list
                            if verified_pid and verified_pid in ns_pids:
                                matching_pids.append(verified_pid)
                                self.log.info(f"PID {verified_pid} from file is in namespace and matches app")
                            
                            # Check other PIDs in namespace for command match
                            for ns_pid in ns_pids:
                                if ns_pid == verified_pid:
                                    continue  # Already added
                                
                                try:
                                    # Check /proc/<pid>/cmdline to see if it matches our app
                                    cmdline_result = self._run(
                                        ["cat", f"/proc/{ns_pid}/cmdline"], no_output=True
                                    )
                                    cmdline = cmdline_result.stdout.replace('\0', ' ')
                                    if base_cmd in cmdline:
                                        matching_pids.append(ns_pid)
                                        self.log.debug(f"Found matching PID {ns_pid} in namespace: {cmdline.strip()}")
                                except RunCommandError:
                                    # Process may have exited, skip it
                                    continue
                        elif verified_pid and verified_pid in ns_pids:
                            # No app_command but we have a verified PID in namespace
                            matching_pids.append(verified_pid)
                        
                        # Step 5: Kill only the matching PIDs that are confirmed in namespace
                        if matching_pids:
                            killed_count = 0
                            for match_pid in matching_pids:
                                try:
                                    self._run(["kill", str(match_pid)])
                                    killed_count += 1
                                    self.log.info(f"Killed PID {match_pid} (app '{app_id}') in namespace {namespace}")
                                except RunCommandError as e:
                                    self.log.warning(f"Failed to kill PID {match_pid} in namespace {namespace}: {e}")
                            
                            if killed_count > 0:
                                self.log.info(f"Successfully stopped {killed_count} process(es) in namespace {namespace}")
                        else:
                            self.log.info(
                                f"No matching processes found in namespace {namespace} "
                                f"(checked {len(ns_pids)} process(es))"
                            )
                            
                    except RunCommandError as e:
                        self.log.error(f"Failed to get PIDs from namespace {namespace}: {e}")
                        # Fallback: if we have a verified PID, try to kill it directly
                        if verified_pid:
                            try:
                                self._run(["kill", str(verified_pid)])
                                self.log.info(f"Killed verified PID {verified_pid} in namespace {namespace} (fallback)")
                            except RunCommandError as kill_err:
                                self.log.warning(f"Fallback kill also failed for PID {verified_pid}: {kill_err}")
                    except Exception as e:
                        self.log.error(f"Unexpected error getting PIDs from namespace {namespace}: {e}")
                        
            except Exception as e:
                self.log.error(f"Failed to stop app in {namespace_display}: {e}", exc_info=True)
            finally:
                pid_file.unlink(missing_ok=True)
        else:
            self.log.warning(f"No PID file found for namespace {namespace_display}.")

    def get_status(self, iface: str, namespace: Optional[str]) -> dict:
        try:
            wpa_status = {}
            wpa = self._ns_exec(
                ["wpa_cli", "-i", iface, "status"], namespace
            ).stdout.strip()
            for line in wpa.split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    wpa_status[key.strip()] = value.strip()

            connected_ssid = wpa_status.get("ssid")
            connected_bssid = wpa_status.get("bssid")

            signal = None
            key_mgmt = "unknown"
            freq = int(wpa_status.get("freq", 0))
            scan = self._ns_exec(
                ["wpa_cli", "-i", iface, "scan_results"], namespace
            ).stdout.strip()
            lines = scan.split("\n")
            if len(lines) > 1 and connected_bssid:
                for line in lines[1:]:
                    parts = line.split("\t")
                    if len(parts) < 5:
                        continue
                    bssid, freq_str, signal_str, flags, ssid = parts
                    if bssid.lower() == connected_bssid.lower():
                        self.log.info(f"found connected network: {parts}")
                        try:
                            signal = int(signal_str)
                        except ValueError:
                            signal = None
                        key_mgmt = self._parse_key_mgmt(flags)
                        break

            ip = self._ns_exec(["ip", "addr", "show", iface], namespace).stdout.strip()

            return {
                "wpa_status": wpa_status,
                "ip_info": ip,
                "connected_scan": {
                    "ssid": connected_ssid,
                    "bssid": connected_bssid,
                    "key_mgmt": key_mgmt,
                    "freq": freq,
                    "signal": signal if isinstance(signal, int) else 0,
                    "minrate": 1000000,
                },
            }

        except RunCommandError as e:
            self.log.warning("Status check failed for %s: %s", iface, e)
            return {"error": str(e)}

    def _parse_key_mgmt(self, flags: str) -> str:
        if "WPA2-PSK" in flags:
            return "wpa-psk"
        elif "WPA-PSK" in flags:
            return "wpa-psk"
        elif "WEP" in flags:
            return "wep"
        elif "[ESS]" in flags and "WPA" not in flags:
            return "open"
        return "unknown"
    
    def _prepare_root(self, cfg: RootConfig):
        try:
            
            iface = cfg.interface

            # Clean up any stale iface
            try:
                self._run(["iw", "dev", iface, "del"])
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
            self.log.error(f"Namespace setup failed for {iface}: {e}")
            raise

    def _prepare_namespace(self, cfg: NamespaceConfig):
        namespace = cfg.namespace
        iface = cfg.interface
        if not namespace:
            return

        try:
            # Make sure the namespace exists
            output = run_command(["ip", "netns", "list"]).stdout
            if namespace in output:
                self.log.info("Namespace %s already exists", namespace)
            else:
                self.log.info("Creating namespace %s", namespace)
                self._run(["sudo", "ip", "netns", "add", namespace])

            # Clean up any stale iface
            try:
                self._ns_exec(["iw", "dev", iface, "del"], namespace)
            except RunCommandError as e:
                if "No such device" in str(e):
                    self.log.info(f"No {iface} to delete in {namespace}. ignoring.")
                else:
                    raise

            phy = cfg.phy

            # Check if phy0 is already in namespace. if yes, move it back to root first
            result = self._ns_exec(["iw", "phy"], namespace, no_output=True)
            if phy in result.stdout:
                self.log.info("Moving phy0 back to root from namespace %s", namespace)
                self._ns_exec(["iw", "phy", phy, "set", "netns", "1"], namespace)
            else:
                self.log.info(
                    f"{phy} not found in {namespace}. assume it's in root already."
                )

            # Attach phy0 to target namespace
            self.log.info(f"Attaching {phy} to namespace {namespace}")
            try:
                self._run(["sudo", "iw", "phy", phy, "set", "netns", "name", namespace])
            except RunCommandError as e:
                self.log.info(f"{phy} does not exist. skipping this config.")
                return False

            # Create the wlan interface
            iface_name = cfg.iface_display_name or iface
            # Get mode value safely (validated, but handle enum vs string)
            mode_value = cfg.mode.value if isinstance(cfg.mode, NetworkModeEnum) else str(cfg.mode)
            try:
                self.log.info(f"adding {iface} as {iface_name} in namespace {namespace}")
                self._ns_exec(
                    ["iw", "phy", phy, "interface", "add", iface_name, "type", mode_value],
                    namespace,
                )
            except:
                self.log.info(f"{iface} already exists")
                
            

            # Bring up the new interface
            self.log.info("Bringing up %s in namespace %s", iface_name, namespace)
            self._ns_exec(["ip", "link", "set", iface_name, "up"], namespace)
            return True

        except RunCommandError as e:
            self.log.error("Namespace setup failed for %s: %s", iface, e)
            raise

   

    def _write_config(self, cfg: Union[NamespaceConfig, RootConfig]):
        iface = cfg.iface_display_name or cfg.interface
        
        # Validate security.ssid exists before accessing
        if not cfg.security or not hasattr(cfg.security, 'ssid') or not cfg.security.ssid:
            raise ValueError("security.ssid is required when writing config with security")
        
        # Fixed: Generate both interface.conf and wlan<index>.conf files
        conf_files = [self.config_dir / f"{iface}.conf"]
        
        # Add wlan<index>.conf if interface follows wlan pattern  
        if iface.startswith("wlan") and len(iface) > 4:
            try:
                index = iface[4:]
                if index.isdigit():
                    conf_files.append(self.config_dir / f"wlan{index}.conf")
            except:
                pass

        for conf_path in conf_files:
            # Find max priority
            max_priority = 0
            blocks = []

            if conf_path.exists():
                with conf_path.open() as f:
                    block, in_block = [], False
                    for line in f:
                        line = line.strip()
                        if line.startswith("network={"):
                            in_block = True
                            block = [line]
                        elif in_block:
                            block.append(line)
                            if line == "}":
                                blocks.append("\n".join(block))
                                in_block = False

                for b in blocks:
                    for l in b.splitlines():
                        if l.strip().startswith("priority="):
                            try:
                                max_priority = max(max_priority, int(l.split("=")[1]))
                            except ValueError:
                                pass

            new_block = self._generate_network_block(cfg, max_priority + 1)
            
            # Fixed: Case-sensitive SSID removal
            original_ssid = cfg.security.ssid
            filtered_blocks = []
            for b in blocks:
                if f'ssid="{original_ssid}"' not in b:
                    filtered_blocks.append(b)
            
            filtered_blocks.insert(0, new_block)

            with conf_path.open("w") as f:
                f.write(self._generate_global_header() + "\n\n" + "\n\n".join(filtered_blocks))

    def _write_dhcp_config(self, iface: str):
        self.dhcp_dir.mkdir(parents=True, exist_ok=True)
        dhcp_path = self.dhcp_dir / f"{iface}.cfg"
        dhcp_path.write_text(
            f"allow-hotplug {iface}\niface {iface} inet dhcp\n"
        )

    def _start_or_restart_supplicant(self, iface: str, namespace: Optional[str]):
        self._ns_exec(["pkill", "-f", f"wpa_supplicant -B -i {iface}"], namespace)
        self._ns_exec(["rm", "-f", f"{self.ctrl_interface}/{iface}"], namespace)
        conf_path = self.config_dir / f"{iface}.conf"
        log_file = Path(f"/tmp/wpa-{iface}.log")
        if log_file.exists():
            log_file.unlink()
        log_file.touch()
        self._ns_exec(
            [
                "wpa_supplicant",
                "-B",
                "-i",
                iface,
                "-c",
                str(conf_path),
                "-D",
                "nl80211",
                "-f",
                f"/tmp/wpa-{iface}.log",
                "-t",
            ],
            namespace,
        )

    def _restart_dhcp_with_timeout(self, iface: str, namespace: Optional[str]):
        """Fixed DHCP with timeout - compatible with older dhclient versions"""
        try:
            # Clean up existing DHCP clients
            self._ns_exec(["dhclient", "-r", iface], namespace)
            self._ns_exec(["pkill", "-f", f"dhclient.*{iface}"], namespace)
            time.sleep(1)
            
            self.log.info("Starting DHCP client for %s with timeout", iface)
            
            # Use timeout command to limit dhclient execution
            dhcp_cmd = ["timeout", "15", "dhclient", "-v", "-1", iface]
            
            try:
                self._ns_exec(dhcp_cmd, namespace)
                self.log.info("DHCP completed for %s", iface)
            except RunCommandError as e:
                if "timeout" in str(e).lower() or "124" in str(e):
                    self.log.info("DHCP timed out for %s - trying alternative config", iface)
                else:
                    self.log.warning("DHCP failed for %s: %s", iface, e)
                
        except Exception as e:
            self.log.warning("DHCP setup had issues for %s: %s", iface, e)

    def _set_default_route(self, iface: str, namespace: Optional[str]):
        try:
            out = self._ns_exec(["ip", "route", "show", "default"], namespace).stdout
        except RunCommandError as e:
            # Treat missing FIB table as no default route yet
            if "FIB table does not exist" in str(e):
                out = ""
            else:
                raise

        if iface not in out:
            try:
                self._ns_exec(
                    [
                        "ip",
                        "route",
                        "replace",
                        "default",
                        "dev",
                        iface,
                        "metric",
                        "200",
                    ],
                    namespace,
                )
            except RunCommandError as e:
                # Log and continue; route setup shouldn't fail activation
                namespace_display = namespace if namespace else "root"
                self.log.warning(f"Could not set default route for {iface} in {namespace_display}: {e}")

    def _generate_global_header(self):
        # Fixed: Correct global settings with SAE support
        lines = [
            f"ctrl_interface={self.global_settings['ctrl_interface']}",
            f"update_config={self.global_settings.get('update_config', 1)}",
            f"sae_pwe=2",  # Fixed: SAE PWE in global context
        ]
        return "\n".join(lines)

    def _generate_network_block(self, cfg: Union[NamespaceConfig, RootConfig], priority=0):
        lines = ["network={"]
        
        # Validate security.ssid exists before accessing
        if not cfg.security or not hasattr(cfg.security, 'ssid') or not cfg.security.ssid:
            raise ValueError("security.ssid is required when generating network block")
        
        # Fixed: Preserve exact SSID case
        original_ssid = cfg.security.ssid
        lines.append(f'    ssid="{original_ssid}"')
        lines.append(f"    priority={priority}")

        # Get security type safely
        if hasattr(cfg.security, 'security') and cfg.security.security:
            sec_str = cfg.security.security.value if isinstance(cfg.security.security, SecurityTypes) else str(cfg.security.security)
            sec = sec_str.upper()
        else:
            sec = "OPEN"

        if sec == "OPEN":
            lines.append("    key_mgmt=NONE")
        elif sec == "OWE":
            lines.append("    key_mgmt=OWE")
            lines.append("    ieee80211w=2")
        elif sec in ("WPA2-PSK", "WPA-PSK"):
            if cfg.security.psk:
                lines.append(f'    psk="{cfg.security.psk}"')
            lines.append("    key_mgmt=WPA-PSK")
            lines.append("    ieee80211w=1")
        elif sec == "WPA3-PSK":
            if cfg.security.psk:
                lines.append(f'    psk="{cfg.security.psk}"')
            lines.append("    key_mgmt=SAE")  # Fixed: WPA3 uses SAE
            lines.append("    ieee80211w=2")  # Fixed: PMF required for WPA3
        elif sec in ("802.1X", "WPA2-EAP", "WPA3-EAP"):
            lines.append("    key_mgmt=WPA-EAP")
            if cfg.security.identity:
                lines.append(f'    identity="{cfg.security.identity}"')
            if cfg.security.password:
                lines.append(f'    password="{cfg.security.password}"')
            
            # Enhanced EAP method support
            eap_method = getattr(cfg.security, 'eap_method', 'PEAP')
            lines.append(f"    eap={eap_method}")
            
            if eap_method == "PEAP":
                phase2_method = getattr(cfg.security, 'phase2_method', 'MSCHAPV2')
                lines.append(f'    phase2="auth={phase2_method}"')
            elif eap_method == "TLS":
                if cfg.security.client_cert:
                    lines.append(f'    client_cert="{cfg.security.client_cert}"')
                if cfg.security.private_key:
                    lines.append(f'    private_key="{cfg.security.private_key}"')
            
            lines.append(f'    ca_cert="{cfg.security.ca_cert or "/etc/ssl/certs/ca-certificates.crt"}"')
            
            if sec == "WPA3-EAP":
                lines.append("    ieee80211w=2")
            else:
                lines.append("    ieee80211w=1")

        if cfg.mlo:
            lines.append("    mlo=1")

        lines.append("}")
        return "\n".join(lines)

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
        if namespace is None:  # None = root namespace
            full_cmd = ["sudo"] + cmd
        else:
            full_cmd = ["sudo", "ip", "netns", "exec", namespace] + cmd
        return self._run(full_cmd, no_output=no_output)

    def _safe_unlink(self, path: Path):
        if path.exists():
            path.unlink()

    def _log_event(self, event: str, timestamp: str):
        self.event_log.append(NetworkEvent(event=event, time=timestamp))

    def kill_all_supplicants(self):
        """Stop any running wpa_supplicant processes across namespaces."""
        try:
            self._run(["sudo", "pkill", "-f", "wpa_supplicant"])  # best-effort
        except RunCommandError:
            pass