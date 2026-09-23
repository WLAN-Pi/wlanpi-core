"""Service managing network namespaces, interfaces, and apps."""

import logging
import os
import re
from pathlib import Path
from typing import Any

from wlanpi_core.adapters import discovery, interface, phy, usage
from wlanpi_core.connection.monitor import (
    ConnectionMonitor,
    stop_all_connection_monitors,
    stop_connection_monitor,
)
from wlanpi_core.constants import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CTRL_INTERFACE,
    DEFAULT_DHCP_DIR,
    NETNS_ETC_DIR,
    NETNS_RUN_DIR,
    PID_DIR,
    RUN_DIR,
)
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.namespaces import (
    apps,
)
from wlanpi_core.namespaces import interfaces as ns_interfaces
from wlanpi_core.namespaces import namespace as ns_namespace
from wlanpi_core.schemas.network.network import (
    NamespaceConfig,
    NetworkEvent,
    NetworkModeEnum,
    NetworkSetupLog,
    NetworkSetupStatus,
    RootConfig,
    ScanItem,
    SecurityTypes,
)
from wlanpi_core.utils.namespace_execution import ns_exec
from wlanpi_core.utils.network_management import (
    set_default_route,
    stop_dhcp,
    stop_namespace_dhcp,
)
from wlanpi_core.wpa import config as wpa_config
from wlanpi_core.wpa import status as wpa_status
from wlanpi_core.wpa import supplicant as wpa_supplicant


class NetworkNamespaceService:
    """Manage network namespaces and their configuration."""

    def __init__(
        self,
        config_dir: str = DEFAULT_CONFIG_DIR,
        ctrl_interface: str = DEFAULT_CTRL_INTERFACE,
        dhcp_dir: str = DEFAULT_DHCP_DIR,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.ctrl_interface = ctrl_interface
        self.dhcp_dir = Path(dhcp_dir)
        self.pid_dir = Path(PID_DIR)
        # PID dir is created lazily when first needed (e.g. in apps.start_app_in_namespace)
        # so that importing this service does not touch the filesystem (CI has no /home/wlanpi).

        # Fixed global settings
        self.global_settings = {
            "ctrl_interface": ctrl_interface,
            "update_config": 1,
        }

        self.log = logging.getLogger(__name__)
        self.event_log: list[NetworkEvent] = []

        # Connection monitoring is now handled by connection.monitor module

    def _validate_config(self, cfg: NamespaceConfig | RootConfig) -> tuple[bool, str]:
        """
        Perform comprehensive validation of config against schema before any state changes.

        Returns (is_valid, error_message)
        """
        errors = []

        # Required fields for RootConfig
        if (
            not hasattr(cfg, "interface")
            or not cfg.interface
            or not isinstance(cfg.interface, str)
        ):
            errors.append("interface is required and must be a non-empty string")
        elif not cfg.interface.strip():
            errors.append("interface cannot be empty or whitespace")

        if not hasattr(cfg, "phy") or not cfg.phy or not isinstance(cfg.phy, str):
            errors.append("phy is required and must be a non-empty string")
        elif not cfg.phy.strip():
            errors.append("phy cannot be empty or whitespace")

        if (
            not hasattr(cfg, "iface_display_name")
            or not cfg.iface_display_name
            or not isinstance(cfg.iface_display_name, str)
        ):
            errors.append(
                "iface_display_name is required and must be a non-empty string"
            )
        elif not cfg.iface_display_name.strip():
            errors.append("iface_display_name cannot be empty or whitespace")

        # Mode validation
        if not hasattr(cfg, "mode"):
            errors.append("mode is required")
        else:
            if not isinstance(cfg.mode, (str, NetworkModeEnum)):
                errors.append(
                    f"mode must be a string or NetworkModeEnum, got {type(cfg.mode)}"
                )
            else:
                mode_str = (
                    cfg.mode.value
                    if isinstance(cfg.mode, NetworkModeEnum)
                    else str(cfg.mode)
                )
                if mode_str not in [e.value for e in NetworkModeEnum]:
                    errors.append(
                        f"mode must be one of {[e.value for e in NetworkModeEnum]}, got '{mode_str}'"
                    )

        # NamespaceConfig specific validation
        if isinstance(cfg, NamespaceConfig):
            if (
                not hasattr(cfg, "namespace")
                or not cfg.namespace
                or not isinstance(cfg.namespace, str)
            ):
                errors.append(
                    "namespace is required for NamespaceConfig and must be a non-empty string"
                )
            elif not cfg.namespace.strip():
                errors.append("namespace cannot be empty or whitespace")

        # Security validation if present
        if cfg.security is not None:
            if (
                not hasattr(cfg.security, "ssid")
                or not cfg.security.ssid
                or not isinstance(cfg.security.ssid, str)
            ):
                errors.append(
                    "security.ssid is required and must be a non-empty string when security is provided"
                )
            elif not cfg.security.ssid.strip():
                errors.append("security.ssid cannot be empty or whitespace")

            if not hasattr(cfg.security, "security") or cfg.security.security is None:
                errors.append("security.security is required when security is provided")
            else:
                if not isinstance(cfg.security.security, (str, SecurityTypes)):
                    errors.append(
                        f"security.security must be a SecurityTypes enum or valid string, got {type(cfg.security.security)}"
                    )
                else:
                    sec_str = (
                        cfg.security.security.value
                        if isinstance(cfg.security.security, SecurityTypes)
                        else str(cfg.security.security)
                    )
                    valid_security = [e.value for e in SecurityTypes]
                    if sec_str not in valid_security:
                        errors.append(
                            f"security.security must be one of {valid_security}, got '{sec_str}'"
                        )

            # Validate security-specific requirements
            if hasattr(cfg.security, "security") and cfg.security.security:
                sec_str = (
                    cfg.security.security.value
                    if isinstance(cfg.security.security, SecurityTypes)
                    else str(cfg.security.security)
                )
                if sec_str in ("WPA2-PSK", "WPA3-PSK", "WPA-PSK"):
                    if (
                        not cfg.security.psk
                        or not isinstance(cfg.security.psk, str)
                        or not cfg.security.psk.strip()
                    ):
                        errors.append(f"security.psk is required for {sec_str}")
                elif sec_str in ("802.1X", "WPA2-EAP", "WPA3-EAP"):
                    if (
                        not cfg.security.identity
                        or not isinstance(cfg.security.identity, str)
                        or not cfg.security.identity.strip()
                    ):
                        errors.append(f"security.identity is required for {sec_str}")
                    if (
                        not cfg.security.password
                        or not isinstance(cfg.security.password, str)
                        or not cfg.security.password.strip()
                    ):
                        errors.append(f"security.password is required for {sec_str}")

        # Optional fields type validation
        if (
            hasattr(cfg, "default_route")
            and cfg.default_route is not None
            and not isinstance(cfg.default_route, bool)
        ):
            errors.append("default_route must be a boolean")

        if hasattr(cfg, "autostart_app") and cfg.autostart_app is not None:
            if not isinstance(cfg.autostart_app, str) or not cfg.autostart_app.strip():
                errors.append("autostart_app must be a non-empty string if provided")

        if (
            hasattr(cfg, "mlo")
            and cfg.mlo is not None
            and not isinstance(cfg.mlo, bool)
        ):
            errors.append("mlo must be a boolean")

        if errors:
            error_msg = "; ".join(errors)
            return False, f"Config validation failed: {error_msg}"

        return True, ""

    def set_global_settings(self, settings: dict[str, Any]) -> None:
        """Update the global wpa_supplicant settings."""
        self.log.info("Updating global settings: %s", settings)
        self.global_settings.update(settings)

    def get_interfaces(self) -> list[Any]:
        """Get list of wireless interfaces using the adapter discovery module."""
        return discovery.list_interfaces()

    def _monitor_connection_async(
        self,
        cfg: NamespaceConfig | RootConfig,
        iface: str,
        namespace: str | None,
        timeout: int = 15,
    ) -> None:
        """
        Start background connection monitor using the connection.monitor module.

        This method delegates to ConnectionMonitor.start_monitor() which handles
        the background monitoring, DHCP, routes, and app startup.
        """
        ConnectionMonitor.start_monitor(cfg, iface, namespace, timeout=timeout)

    def stop_connection_monitor(self, namespace: str | None, iface: str) -> None:
        """
        Stop a connection monitor for a specific interface/namespace.

        Delegates to connection.monitor module.
        """
        stop_connection_monitor(namespace, iface)

    def stop_all_connection_monitors(self) -> None:
        """
        Stop all active connection monitors. Useful for shutdown or cleanup.

        Delegates to connection.monitor module.
        """
        stop_all_connection_monitors()

    def activate_config(self, cfg: NamespaceConfig | RootConfig) -> NetworkSetupStatus:
        """
        Activate a network configuration.

        Returns a NetworkSetupStatus. Performs comprehensive validation before
        any state changes.
        """
        # Validate config before any state changes
        is_valid, error_msg = self._validate_config(cfg)
        if not is_valid:
            self.log.error(
                f"Config validation failed, aborting activation: {error_msg}"
            )
            log = NetworkSetupLog(selectErr=error_msg, eventLog=self.event_log)
            return NetworkSetupStatus(
                status="error",
                response=log,
                connectedNet=None,
                input=cfg.__str__(),
            )

        # Safe to access fields after validation
        iface = cfg.interface
        namespace = (
            cfg.namespace if isinstance(cfg, NamespaceConfig) else None
        )  # None = root namespace

        # Resolve the live netdev (any netns, either name) before any state change
        live = self._find_live(cfg)
        self.log.info(f"Live interface for {iface}: {live}")

        if live is None:
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

        # Never take a radio another tool is using; the rest of the profile
        # still runs and the outcome says why this entry did not.
        reason = self.in_use_reason(live)
        if reason is not None:
            self.log.warning(f"Not activating {iface}: {reason}")
            log = NetworkSetupLog(selectErr=reason, eventLog=self.event_log)
            return NetworkSetupStatus(
                status="in_use",
                response=log,
                connectedNet=None,
                input=cfg.__str__(),
            )

        namespace_display = namespace if namespace else "root"
        self.log.info("Adding network on %s in namespace %s", iface, namespace_display)

        # Prepare namespace or root - this is the first state change
        if isinstance(cfg, NamespaceConfig):
            success = self._prepare_namespace(cfg, live)
        else:
            success = self._prepare_root(cfg, live)

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

        # From here the radio is configured; if anything below fails, put it
        # back rather than leave it moved and recreated in the new mode.
        try:
            # Use display name if available, otherwise fall back to interface
            iface = cfg.iface_display_name or iface
            connected_state = False

            if cfg.security:
                # Additional validation: ensure ssid exists (should be caught by validation, but double-check)
                if not hasattr(cfg.security, "ssid") or not cfg.security.ssid:
                    error_msg = "security.ssid is required when security is provided"
                    self.log.error(error_msg)
                    log = NetworkSetupLog(selectErr=error_msg, eventLog=self.event_log)
                    return NetworkSetupStatus(
                        status="error",
                        response=log,
                        connectedNet=None,
                        input=cfg.__str__(),
                    )

                wpa_config.write_wpa_config(
                    cfg,
                    wpa_supplicant.config_path(iface, namespace),
                    self.global_settings,
                    self._ctrl_dir(namespace),
                )
                wpa_supplicant.start_or_restart_supplicant(iface, namespace)

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
                apps.start_app_in_namespace(
                    namespace, cfg.autostart_app, pid_dir=self.pid_dir
                )

        except Exception as e:
            self.log.error(f"Setup after prepare failed for {iface}: {e}; reverting it")
            try:
                self.revert_to_root(cfg)
            except Exception as revert_error:
                self.log.error(f"Could not revert {iface}: {revert_error}")
            raise

        connected = None
        # For security configs with async monitoring, always return "provisioned" initially
        # The background monitor will handle connection completion
        if cfg.security:
            status_value = "provisioned"
        else:
            status_value = "connected"

        # Get mode value safely (validated, but handle enum vs string)
        mode_value = (
            cfg.mode.value if isinstance(cfg.mode, NetworkModeEnum) else str(cfg.mode)
        )

        # Only check status for non-security configs or monitor mode
        # For security configs, connection is happening asynchronously
        if mode_value != "monitor" and not cfg.security:
            status = self.get_status(iface, namespace)
            wpa: dict[str, Any] = status.get("wpa_status", {})
            scan: dict[str, Any] = status.get("connected_scan", {})

            if (
                hasattr(cfg, "security")
                and cfg.security
                and hasattr(cfg.security, "ssid")
                and cfg.security.ssid
            ):
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

    def deactivate_config(self, cfg: NamespaceConfig | RootConfig) -> None:
        """Deactivate a network configuration and revert to root."""
        iface = cfg.iface_display_name or cfg.interface
        namespace = (
            cfg.namespace if isinstance(cfg, NamespaceConfig) else None
        )  # None = root namespace

        # Stop any active connection monitor for this config
        self.stop_connection_monitor(namespace, iface)

        # Check if interface exists in any netns before trying to deactivate
        if self._find_live(cfg) is None:
            self.log.info(f"Interface {iface} does not exist, skipping deactivation")
            return

        if cfg.autostart_app:
            apps.stop_app_in_namespace(namespace, pid_dir=self.pid_dir)
        if cfg.security:
            try:
                self.remove_network(iface, namespace)
            except RunCommandError as e:
                namespace_display = namespace if namespace else "root"
                self.log.warning(
                    f"Failed to remove network {iface} in namespace {namespace_display}: {e} (non-critical)"
                )

        self.revert_to_root(cfg)

    def remove_network(self, iface: str, namespace: str | None) -> None:
        """Remove a network configuration from a namespace."""
        namespace_display = namespace if namespace else "root"
        self.log.info("Removing network %s from namespace %s", iface, namespace_display)

        # Runtime config and log, plus the wlanN.conf / wlanN.cfg that Core
        # wrote under /etc before runtime state moved to /run. Only that exact
        # name pattern: a display name such as "wpa_supplicant" must never
        # remove /etc/wpa_supplicant/wpa_supplicant.conf.
        stale = [
            wpa_supplicant.config_path(iface, namespace),
            wpa_supplicant.log_path(iface, namespace),
        ]
        if re.fullmatch(r"wlan[0-9]+", iface):
            stale.append(self.config_dir / f"{iface}.conf")
            stale.append(self.dhcp_dir / f"{iface}.cfg")
        for config_file in stale:
            self._safe_unlink(config_file)

        wpa_supplicant.stop_supplicant(iface, namespace)
        self._safe_unlink(Path(self._ctrl_dir(namespace)) / iface)
        stop_dhcp(iface, namespace)

    def revert_to_root(
        self,
        cfg: NamespaceConfig | RootConfig | None = None,
        delete_namespace: bool = True,
    ) -> None:
        """Move interfaces and PHYs back to the root namespace."""
        # No cfg: return every phy in every namespace Core created
        if cfg is None:
            for ns_name in self.core_namespaces():
                self._return_namespace_phys(ns_name)
                if delete_namespace:
                    self._delete_namespace_if_empty(ns_name)
            return

        iface = cfg.interface

        # Resolve where the netdev really is; cfg.namespace and cfg.phy can be stale
        live = self._find_live(cfg)
        if live is None:
            self.log.info(f"Interface {iface} does not exist, skipping revert")
            return
        namespace = live.netns
        namespace_display = namespace if namespace else "root"

        self.log.info(
            f"Reverting {live.name} ({live.phy}) from namespace {namespace_display} to root namespace."
        )

        # Stop the supplicant and DHCP client tied to this interface
        wpa_supplicant.stop_supplicant(live.name, namespace)
        self._safe_unlink(Path(self._ctrl_dir(namespace)) / live.name)
        stop_dhcp(live.name, namespace)

        if namespace is None:
            # Root entry: put the radio back as `interface`, managed, so the
            # profile's name and mode do not outlive it (#288).
            if live.name != iface or live.type != "managed":
                self._recreate_in_root(live, iface)
            else:
                self._release(live.name, None)
            return

        self._recreate_in_root(live, iface)
        self.log.info(f"Reverted {iface} on {live.phy} to root namespace.")

        # Delete the namespace only if Core created it and nothing is left in it
        if delete_namespace and namespace in self.core_namespaces():
            self._delete_namespace_if_empty(namespace)

    def _recreate_in_root(self, live: discovery.LiveInterface, name: str) -> None:
        """Delete `live`, return its phy to root, and recreate it as managed `name`.

        Each step is checked: if one fails, the original netdev is restored
        and the error propagates, so a revert that did not happen is never
        reported as done and its namespace is not deleted. The result is
        handed back: Core no longer owns it.
        """
        self._release(live.name, live.netns)
        # A failed delete changes nothing; let it propagate as is.
        interface.delete_interface(live.name, namespace=live.netns)
        moved_to = live.netns
        try:
            if live.netns is not None:
                phy.move_phy_to_root(live.phy, live.netns)
                moved_to = None
            interface.create_interface(
                live.phy, name, interface_type="managed", namespace=None
            )
            interface.bring_interface_up(name, namespace=None)
        except RunCommandError as e:
            self.log.error(f"Could not return {live.name} on {live.phy} to root: {e}")
            self._restore_live(live, name, moved_to, None)
            raise

    def _ctrl_dir(self, namespace: str | None) -> str:
        """Return the control socket directory for a supplicant in `namespace`."""
        return (
            self.ctrl_interface
            if namespace is None
            else wpa_supplicant.ctrl_dir(namespace)
        )

    def _namespace_marker(self, namespace: str) -> Path:
        # /run is tmpfs, like /run/netns, so a marker lives as long as its netns.
        return Path(RUN_DIR) / "netns" / namespace

    def _netns_id(self, namespace: str) -> str | None:
        """Return the identity (inode) of a named netns, or None if it is gone."""
        try:
            return str(os.stat(Path(NETNS_RUN_DIR) / namespace).st_ino)
        except OSError:
            return None

    # --- netdevs Core created ---
    #
    # Core deletes and recreates every netdev it configures, so "created by
    # Core" is exactly "Core's responsibility". Automatic changes (the default
    # configuration) only touch those; netdevs from drivers or other tools
    # (hostapd, wlanpi-profiler, a user's mon0) are left alone. Keyed by
    # (netns, name) and checked against the ifindex, which a netns move keeps
    # and a recreate by anyone else changes. On tmpfs, so a reboot resets it.
    # A netdev is owned only while a profile uses it: reverting an entry hands
    # it back, since another tool may take it over without recreating it
    # (wlanpi-profiler reuses the netdev, keeping its ifindex).

    def _owned_path(self, name: str, netns: str | None) -> Path:
        return Path(RUN_DIR) / "owned" / (netns or "@root") / name

    def _claim(self, name: str, netns: str | None) -> None:
        """Record the netdev Core just created as Core's."""
        for live in discovery.list_interfaces_all_namespaces():
            if live.name == name and live.netns == netns and live.ifindex is not None:
                path = self._owned_path(name, netns)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(live.ifindex))
                return

    def _release(self, name: str, netns: str | None) -> None:
        """Hand a netdev back: Core no longer owns it."""
        self._owned_path(name, netns).unlink(missing_ok=True)

    def _is_owned(self, live: discovery.LiveInterface) -> bool:
        try:
            recorded = self._owned_path(live.name, live.netns).read_text().strip()
        except OSError:
            return False
        return live.ifindex is not None and recorded == str(live.ifindex)

    def in_use_reason(self, live: discovery.LiveInterface) -> str | None:
        """Return why another tool is using `live`'s radio, or None if it is free.

        In use means: a mode Core never sets (e.g. AP), a wpa_supplicant or
        hostapd Core did not start bound to it, or a program capturing on
        another netdev of the same radio that Core did not create.
        """
        if live.type and live.type not in usage.CORE_MODES:
            return f"{live.name} is in {live.type} mode, set by another tool"
        users = usage.foreign_users(live.name, live.netns)
        if users:
            return f"{live.name} is used by {', '.join(users)}"
        siblings = [
            other
            for other in discovery.list_interfaces_all_namespaces()
            if other.phy_index == live.phy_index
            and other.netns == live.netns
            and other.name != live.name
            and not self._is_owned(other)
        ]
        if siblings:
            capturing = usage.capturing_links(live.netns)
            for other in siblings:
                if other.ifindex in capturing:
                    return (
                        f"{other.name} on the same radio ({live.phy}) is in use "
                        "(a program is capturing on it)"
                    )
        return None

    def is_core_managed(self, cfg: NamespaceConfig | RootConfig) -> bool:
        """Return whether automatic changes may touch cfg's radio.

        True for a netdev Core created, a radio in a namespace Core created,
        or a radio that is not present (activation just skips it).
        """
        live = self._find_live(cfg)
        if live is None:
            return True
        if live.netns is not None:
            return live.netns in self.core_namespaces()
        return self._is_owned(live)

    def may_undo(self, cfg: NamespaceConfig | RootConfig) -> bool:
        """Return whether tearing a profile down may revert cfg's radio.

        Only what Core set up: a radio in a namespace Core created, or a root
        netdev Core created. An entry left alone as in_use was never Core's.
        A Core netdev that another tool has since started using is handed
        back instead of reverted, so that tool keeps it.
        """
        live = self._find_live(cfg)
        if live is None:
            return True
        if live.netns is not None:
            return live.netns in self.core_namespaces()
        if not self._is_owned(live):
            return False
        reason = self.in_use_reason(live)
        if reason is not None:
            self.log.warning(f"Leaving {live.name} as it is: {reason}")
            self._release(live.name, None)
            return False
        return True

    def core_namespaces(self) -> list[str]:
        """Return the existing namespaces that Core created, dropping stale markers."""
        marker_dir = Path(RUN_DIR) / "netns"
        if not marker_dir.is_dir():
            return []
        try:
            existing = set(ns_namespace.list_namespaces())
        except ns_namespace.NetworkNamespaceError as e:
            self.log.warning(f"Failed to list namespaces: {e}")
            return []
        owned = []
        for marker in sorted(marker_dir.iterdir()):
            if marker.name in existing:
                recorded = marker.read_text().strip()
                if recorded and recorded == self._netns_id(marker.name):
                    owned.append(marker.name)
                else:
                    # Same name, different namespace (deleted and recreated
                    # by someone else): not Core's. Leave its /etc alone.
                    marker.unlink(missing_ok=True)
            else:
                # Deleted out of band: drop the marker and Core's /etc overlay
                marker.unlink(missing_ok=True)
                self._remove_netns_etc(marker.name)
        return owned

    def _remove_netns_etc(self, namespace: str) -> None:
        """Remove the resolv.conf Core wrote for `namespace`, and its dir if empty."""
        etc_dir = Path(NETNS_ETC_DIR) / namespace
        (etc_dir / "resolv.conf").unlink(missing_ok=True)
        try:
            etc_dir.rmdir()
        except OSError:
            pass  # absent, or holds files Core did not write

    def _return_namespace_phys(self, namespace: str) -> None:
        """Stop Core's supplicants in `namespace` and move every phy in it to root."""
        self.log.info(f"Returning phys in namespace {namespace} to root")
        wpa_supplicant.stop_namespace_supplicants(namespace)
        stop_namespace_dhcp(namespace)
        try:
            phys = phy.list_phys(namespace=namespace)
        except RunCommandError as e:
            self.log.warning(f"Could not list phys in {namespace}: {e}")
            return
        inventory = discovery.list_interfaces_all_namespaces()
        for phy_name in phys:
            travelling = [
                live
                for live in inventory
                if live.netns == namespace
                and f"phy{live.phy_index}" == phy_name
                and self._is_owned(live)
            ]
            try:
                phy.move_phy_to_root(phy_name, namespace)
                self.log.info(f"Moved {phy_name} from namespace {namespace} to root")
            except RunCommandError as e:
                self.log.warning(f"Could not move {phy_name} from {namespace}: {e}")
                continue
            # Core's netdevs travel home with the phy and are handed back.
            for live in travelling:
                self._release(live.name, namespace)

    def _delete_namespace_if_empty(self, namespace: str) -> None:
        """Delete a Core namespace once no phys or non-loopback links remain."""
        self.stop_app_in_namespace(namespace)
        try:
            remaining = phy.list_phys(
                namespace=namespace
            ) + ns_interfaces.get_interfaces_in_namespace(
                namespace, include_loopback=False
            )
        except RunCommandError as e:
            self.log.warning(f"Could not inspect namespace {namespace}: {e}")
            return
        if remaining:
            self.log.warning(f"Keeping namespace {namespace}; still holds {remaining}")
            return
        ns_namespace.delete_namespace(namespace, raise_on_fail=False)
        if ns_namespace.namespace_exists(namespace):
            # Keep the marker so Core still owns (and retries) it.
            self.log.warning(f"Could not delete namespace {namespace}")
            return
        self._namespace_marker(namespace).unlink(missing_ok=True)
        self._remove_netns_etc(namespace)
        self.log.info(f"Deleted namespace {namespace}.")

    def start_app_in_namespace(self, namespace: str | None, app_id: str) -> None:
        """
        Start an application in a namespace or root namespace.

        Delegates to namespaces.apps module.
        """
        apps.start_app_in_namespace(namespace, app_id, pid_dir=self.pid_dir)

    def stop_app_in_namespace(self, namespace: str | None) -> None:
        """
        Stop an application running in a namespace or root namespace.

        Delegates to namespaces.apps module.
        """
        apps.stop_app_in_namespace(namespace, pid_dir=self.pid_dir)

    def get_status(self, iface: str, namespace: str | None) -> dict[str, Any]:
        """
        Get network status for an interface.

        Delegates to wpa.status module.
        """
        return wpa_status.get_wpa_status(iface, namespace)

    def _find_live(
        self, cfg: NamespaceConfig | RootConfig
    ) -> discovery.LiveInterface | None:
        """Find the live netdev backing cfg, in any namespace.

        `interface` names the radio, so it is looked up first, wherever the
        radio is. Only if no netdev has that name (Core renamed it on an
        earlier activation) is `iface_display_name` tried, and only in cfg's
        own target namespace: another entry may use the same display name
        elsewhere, and another radio may already carry that name. Radios in
        namespaces Core did not create (other than cfg's own target) are not
        considered.
        """
        namespace = cfg.namespace if isinstance(cfg, NamespaceConfig) else None
        # Radios in namespaces Core did not create belong to someone else;
        # treat them like an unplugged adapter rather than taking them.
        owned = set(self.core_namespaces())
        inventory = [
            live
            for live in discovery.list_interfaces_all_namespaces()
            if live.netns is None or live.netns in owned or live.netns == namespace
        ]
        matches = sorted(
            (live for live in inventory if live.name == cfg.interface),
            key=lambda live: (live.netns != namespace, live.netns is not None),
        )
        if len(matches) > 1:
            self.log.warning(
                f"Interface {cfg.interface} exists in several namespaces "
                f"{[m.netns or 'root' for m in matches]}; using {matches[0].netns or 'root'}"
            )
        if matches:
            return matches[0]
        display = cfg.iface_display_name
        if display and display != cfg.interface:
            for live in inventory:
                if live.name == display and live.netns == namespace:
                    return live
        return None

    def _mode_value(self, cfg: NamespaceConfig | RootConfig) -> str:
        return (
            cfg.mode.value if isinstance(cfg.mode, NetworkModeEnum) else str(cfg.mode)
        )

    def _warn_stale_phy(
        self, cfg: NamespaceConfig | RootConfig, live: discovery.LiveInterface
    ) -> None:
        if cfg.phy != f"phy{live.phy_index}":
            self.log.warning(
                f"Config says {cfg.interface} is on {cfg.phy}, but {live.name} is on "
                f"{live.phy}; using the live phy."
            )

    def _restore_live(
        self,
        live: discovery.LiveInterface,
        new_name: str,
        moved_to: str | None,
        created_namespace: str | None,
    ) -> None:
        """Best-effort undo of a prepare that failed after deleting `live`.

        Removes a half-created `new_name` from where the phy is now (only if
        it is on this phy), moves the phy back to its original netns, and
        recreates the original netdev.
        """
        try:
            # Remove a half-created `new_name` only if it is on our phy: the
            # create may have failed because another radio owns that name.
            ours = any(
                other.name == new_name
                and other.netns == moved_to
                and other.phy_index == live.phy_index
                for other in discovery.list_interfaces_all_namespaces()
            )
            if ours:
                interface.delete_interface(new_name, namespace=moved_to)
            if moved_to != live.netns:
                if moved_to is not None:
                    phy.move_phy_to_root(live.phy, moved_to)
                if live.netns is not None:
                    phy.move_phy_to_namespace(live.phy, live.netns)
            interface.create_interface(
                live.phy,
                live.name,
                interface_type=live.type or "managed",
                namespace=live.netns,
            )
        except RunCommandError as e:
            self.log.error(f"Could not restore {live.name} on {live.phy}: {e}")
        if created_namespace is not None:
            self._delete_namespace_if_empty(created_namespace)

    def _prepare_root(self, cfg: RootConfig, live: discovery.LiveInterface) -> bool:
        """
        Recreate cfg's interface in the root namespace on its live phy.

        The live netdev is resolved before anything is deleted, so a stale
        cfg.phy never costs the radio its netdev. On failure the original
        netdev is restored before the error propagates.
        """
        self._warn_stale_phy(cfg, live)
        iface_name = cfg.iface_display_name or cfg.interface
        moved_to = live.netns
        interface.delete_interface(live.name, namespace=live.netns)
        if live.netns is not None:
            self.log.info(f"Attaching {live.phy} to root namespace")
            try:
                phy.move_phy_to_root(live.phy, live.netns)
            except RunCommandError as e:
                self.log.error(f"Could not move {live.phy} to root: {e}")
                self._restore_live(live, iface_name, moved_to, None)
                return False
            moved_to = None
        try:
            self.log.info(f"adding {iface_name} on {live.phy} in root")
            interface.create_interface(
                live.phy, iface_name, interface_type=self._mode_value(cfg)
            )
            self.log.info("Bringing up %s in root", iface_name)
            interface.bring_interface_up(iface_name, namespace=None)
        except RunCommandError as e:
            self.log.error(f"Root setup failed for {iface_name}: {e}")
            self._restore_live(live, iface_name, moved_to, None)
            raise
        self._claim(iface_name, None)
        return True

    def _prepare_namespace(
        self, cfg: NamespaceConfig, live: discovery.LiveInterface
    ) -> bool | None:
        """
        Move cfg's live phy into cfg.namespace and recreate the interface there.

        The netdev is deleted where it lives before the phy moves, so it
        cannot travel into the namespace under its old name and mode. On
        failure the original netdev is restored and a namespace created here
        is removed before the error propagates.
        """
        namespace = cfg.namespace
        if not namespace:
            return None
        self._warn_stale_phy(cfg, live)
        iface_name = cfg.iface_display_name or cfg.interface

        created_namespace = None
        if not ns_namespace.namespace_exists(namespace):
            self.log.info("Creating namespace %s", namespace)
            ns_namespace.create_namespace(namespace)
            try:
                # The marker records the namespace's identity, so a later
                # namespace of the same name made by another tool is not
                # mistaken for Core's.
                marker = self._namespace_marker(namespace)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(self._netns_id(namespace) or "")
                # `ip netns exec` bind-mounts /etc/netns/<ns>/resolv.conf over
                # /etc/resolv.conf, so DHCP in the namespace cannot rewrite
                # root DNS. Empty, not touched: a namespace reusing this name
                # must not inherit the previous one's nameservers.
                etc_dir = Path(NETNS_ETC_DIR) / namespace
                etc_dir.mkdir(parents=True, exist_ok=True)
                (etc_dir / "resolv.conf").write_text("")
            except OSError:
                ns_namespace.delete_namespace(namespace, raise_on_fail=False)
                self._namespace_marker(namespace).unlink(missing_ok=True)
                raise
            created_namespace = namespace
        else:
            self.log.info("Namespace %s already exists", namespace)

        moved_to = live.netns
        interface.delete_interface(live.name, namespace=live.netns)
        if live.netns != namespace:
            try:
                if live.netns is not None:
                    phy.move_phy_to_root(live.phy, live.netns)
                    moved_to = None
                self.log.info(f"Attaching {live.phy} to namespace {namespace}")
                phy.move_phy_to_namespace(live.phy, namespace)
            except RunCommandError as e:
                self.log.error(f"Could not move {live.phy} to {namespace}: {e}")
                self._restore_live(live, iface_name, moved_to, created_namespace)
                return False
            moved_to = namespace
        try:
            self.log.info(f"adding {iface_name} on {live.phy} in namespace {namespace}")
            interface.create_interface(
                live.phy,
                iface_name,
                interface_type=self._mode_value(cfg),
                namespace=namespace,
            )
            self.log.info("Bringing up %s in namespace %s", iface_name, namespace)
            interface.bring_interface_up(iface_name, namespace=namespace)
        except RunCommandError as e:
            self.log.error("Namespace setup failed for %s: %s", iface_name, e)
            self._restore_live(live, iface_name, moved_to, created_namespace)
            raise
        self._claim(iface_name, namespace)
        return True

    def _ns_exec(
        self, cmd: list[str], namespace: str | None, no_output: bool = False
    ) -> Any:
        """
        Execute a command in a namespace or root namespace.

        This method wraps the namespace execution utility, adding service-level
        logging. For direct namespace execution, use wlanpi_core.utils.namespace_execution.ns_exec.
        """
        # Use the extracted utility, but wrap with service-level logging
        try:
            result = ns_exec(
                cmd, namespace=namespace, no_output=no_output, raise_on_fail=True
            )
            if not no_output:
                self.log.info(
                    f"Command succeeded in namespace '{namespace or 'root'}': {' '.join(cmd)}"
                )
            return result
        except RunCommandError as e:
            self.log.error(
                f"Command failed in namespace '{namespace or 'root'}': {' '.join(cmd)} - {e}"
            )
            raise

    def _safe_unlink(self, path: Path) -> None:
        if path.exists():
            path.unlink()

    def _log_event(self, event: str, timestamp: str | None = None) -> None:
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

    def kill_all_supplicants(self) -> None:
        """
        Stop every wpa_supplicant Core started, across namespaces.

        Delegates to wpa.supplicant module.
        """
        wpa_supplicant.kill_all_supplicants()
