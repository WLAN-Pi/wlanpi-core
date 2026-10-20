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
    MONITOR_IFACE_PREFIX,
    NETNS_ETC_DIR,
    NETNS_RUN_DIR,
    PID_DIR,
    ROOT_NS_DIR_NAME,
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
    SecurityTypes,
)
from wlanpi_core.utils.network_management import (
    stop_dhcp,
    stop_namespace_dhcp,
)
from wlanpi_core.utils.validation import validate_namespace_name
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
        # Not created here: importing this service must not touch the filesystem.
        self.pid_dir = Path(PID_DIR)
        self.global_settings = {
            "ctrl_interface": ctrl_interface,
            "update_config": 1,
        }

        self.log = logging.getLogger(__name__)
        self.event_log: list[NetworkEvent] = []

    def validate_config(self, cfg: NamespaceConfig | RootConfig) -> tuple[bool, str]:
        """Validate cfg before any state change; return (is_valid, error_message)."""
        errors = []

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

        if (
            hasattr(cfg, "default_route")
            and cfg.default_route is not None
            and not isinstance(cfg.default_route, bool)
        ):
            errors.append("default_route must be a boolean")

        if hasattr(cfg, "autostart_app") and cfg.autostart_app is not None:
            if not isinstance(cfg.autostart_app, str) or not cfg.autostart_app.strip():
                errors.append("autostart_app must be a non-empty string if provided")
            else:
                # Fail before any radio moves, not after (#311).
                try:
                    if not apps.get_app_command(cfg.autostart_app):
                        errors.append(
                            f"autostart_app '{cfg.autostart_app}' is not defined in {apps.APPS_FILE}"
                        )
                except (OSError, ValueError) as e:
                    errors.append(f"cannot read apps file: {e}")

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
        """Start the background connection monitor for cfg."""
        ConnectionMonitor.start_monitor(cfg, iface, namespace, timeout=timeout)

    def stop_connection_monitor(self, namespace: str | None, iface: str) -> None:
        """Stop the connection monitor for `iface` in `namespace`."""
        stop_connection_monitor(namespace, iface)

    def stop_all_connection_monitors(self) -> None:
        """Stop all active connection monitors."""
        stop_all_connection_monitors()

    def activate_config(self, cfg: NamespaceConfig | RootConfig) -> NetworkSetupStatus:
        """Validate and activate one configuration entry."""
        is_valid, error_msg = self.validate_config(cfg)
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

        iface = cfg.interface
        namespace = cfg.namespace if isinstance(cfg, NamespaceConfig) else None

        live = self._find_live(cfg)
        self.log.info(f"Live interface for {iface}: {live}")

        if live is None:
            skip_msg = f"Interface '{iface}' does not exist, skipping activation for this config."
            self.log.info(skip_msg)
            log = NetworkSetupLog(selectErr=skip_msg, eventLog=self.event_log)
            # Provisioned, not error, so the profile's other entries still activate.
            return NetworkSetupStatus(
                status="provisioned",
                response=log,
                connectedNet=None,
                input=cfg.__str__(),
            )

        # Never take a radio another tool is using; the outcome says why.
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

        # The radio is moved now: on any failure below, revert it.
        try:
            iface = cfg.iface_display_name or iface

            if cfg.security:
                wpa_config.write_wpa_config(
                    cfg,
                    wpa_supplicant.config_path(iface, namespace),
                    self.global_settings,
                    self._ctrl_dir(namespace),
                )
                wpa_supplicant.start_or_restart_supplicant(iface, namespace)

                self.log.info(
                    f"Started wpa_supplicant for {iface} in {namespace_display}. "
                    f"Connection will be monitored in background. Returning with 'provisioned' status."
                )
                self._monitor_connection_async(cfg, iface, namespace, timeout=15)

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

        if cfg.security:
            status_value = "provisioned"
        else:
            status_value = "connected"

        mode_value = (
            cfg.mode.value if isinstance(cfg.mode, NetworkModeEnum) else str(cfg.mode)
        )

        if mode_value != "monitor" and not cfg.security:
            status = self.get_status(iface, namespace)
            wpa: dict[str, Any] = status.get("wpa_status", {})

            wpa_state = (wpa.get("wpa_state") or "").upper()
            if wpa_state != "COMPLETED":
                status_value = "provisioned"

        log = NetworkSetupLog(selectErr="", eventLog=self.event_log)
        return NetworkSetupStatus(
            status=status_value,
            response=log,
            connectedNet=None,
            input=cfg.__str__(),
        )

    def deactivate_config(self, cfg: NamespaceConfig | RootConfig) -> None:
        """Stop Core's processes for cfg, then revert its radio if Core may.

        An entry Core never set up is not touched. Otherwise the monitor, app,
        wpa_supplicant and dhcpcd are stopped through Core's pidfiles, even when
        the netdev is gone; the radio is reverted only when may_undo allows (#304).
        """
        iface = cfg.iface_display_name or cfg.interface
        namespace = cfg.namespace if isinstance(cfg, NamespaceConfig) else None

        live = self._find_live(cfg)
        if live is not None and not self.is_core_managed(cfg):
            self.log.info(f"Leaving {iface} alone: not set up by Core")
            return

        self.stop_connection_monitor(namespace, iface)
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

        if live is None:
            self.log.info(f"Interface {iface} does not exist, nothing to revert")
            return
        if self.may_undo(cfg):
            self.revert_to_root(cfg)

    def remove_network(self, iface: str, namespace: str | None) -> None:
        """Remove a network configuration from a namespace."""
        namespace_display = namespace if namespace else "root"
        self.log.info("Removing network %s from namespace %s", iface, namespace_display)

        # Legacy /etc files by exact wlanN name only: a display name like
        # "wpa_supplicant" must never remove /etc/wpa_supplicant/wpa_supplicant.conf.
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
        # Shared default ctrl dir: keep the socket of a supplicant that took the netdev.
        if not usage.foreign_users(iface, namespace):
            self._safe_unlink(Path(self._ctrl_dir(namespace)) / iface)
        stop_dhcp(iface, namespace)

    def revert_to_root(
        self,
        cfg: NamespaceConfig | RootConfig | None = None,
        delete_namespace: bool = True,
    ) -> None:
        """Move interfaces and PHYs back to the root namespace."""
        if cfg is None:
            for ns_name in self.core_namespaces():
                self._return_namespace_phys(ns_name)
                if delete_namespace:
                    self._delete_namespace_if_empty(ns_name)
            return

        iface = cfg.interface

        # cfg.namespace and cfg.phy can be stale.
        live = self._find_live(cfg)
        if live is None:
            self.log.info(f"Interface {iface} does not exist, skipping revert")
            return
        namespace = live.netns
        namespace_display = namespace if namespace else "root"

        self.log.info(
            f"Reverting {live.name} ({live.phy}) from namespace {namespace_display} to root namespace."
        )

        wpa_supplicant.stop_supplicant(live.name, namespace)
        self._safe_unlink(Path(self._ctrl_dir(namespace)) / live.name)
        stop_dhcp(live.name, namespace)

        if namespace is None:
            # The profile's name and mode must not outlive it (#288).
            if live.name != iface or live.type != "managed":
                self._recreate_in_root(live, iface)
            else:
                self._take_down(live.name)
                self._release(live.name, None)
            return

        self._recreate_in_root(live, iface)
        self.log.info(f"Reverted {iface} on {live.phy} to root namespace.")

        if delete_namespace and namespace in self.core_namespaces():
            self._delete_namespace_if_empty(namespace)

    def _take_down(self, name: str) -> None:
        """Bring a root managed netdev Core hands back down, best effort.

        Up with no supplicant, cfg80211 refuses channel changes on the radio's monitor.
        """
        try:
            interface.bring_interface_down(name, namespace=None)
        except RunCommandError as e:
            self.log.warning(f"Could not bring {name} down: {e}")

    def _recreate_in_root(self, live: discovery.LiveInterface, name: str) -> None:
        """Delete `live`, return its phy to root, and recreate it as managed `name`, unowned.

        On a failed step the original netdev is restored and the error propagates.
        """
        self._release(live.name, live.netns)
        # A failed delete changes nothing; let it propagate as is.
        interface.delete_interface(live.name, namespace=live.netns)
        moved_to = live.netns
        try:
            if live.netns is not None:
                phy.move_phy_to_root(live.phy, live.netns)
                moved_to = None
            # Left down, as at boot (see _take_down).
            interface.create_interface(
                live.phy, name, interface_type="managed", namespace=None
            )
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

    # Ownership is the cfg80211 wdev id: a netns move keeps it, anyone else's recreate changes it.
    def _owned_path(self, name: str, netns: str | None) -> Path:
        return Path(RUN_DIR) / "owned" / (netns or ROOT_NS_DIR_NAME) / name

    def _claim(self, name: str, netns: str | None) -> None:
        """Record the netdev Core just created as Core's."""
        for live in discovery.list_interfaces_all_namespaces():
            if live.name == name and live.netns == netns and live.wdev is not None:
                path = self._owned_path(name, netns)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(live.wdev)
                return

    def _release(self, name: str, netns: str | None) -> None:
        """Hand a netdev back: Core no longer owns it."""
        self._owned_path(name, netns).unlink(missing_ok=True)

    def _is_owned(self, live: discovery.LiveInterface) -> bool:
        """Return whether Core created `live` (same name and wdev id).

        A netdev moved out of band (e.g. its phy moved back to root by hand)
        keeps its wdev; its record is found under the old namespace and
        re-keyed to where the netdev is now.
        """
        if live.wdev is None:
            return False
        here = self._owned_path(live.name, live.netns)
        for path in [here, *sorted(here.parent.parent.glob(f"*/{live.name}"))]:
            try:
                if path.read_text().strip() != live.wdev:
                    continue
            except OSError:
                continue
            if path != here:
                here.parent.mkdir(parents=True, exist_ok=True)
                path.replace(here)
            return True
        return False

    def in_use_reason(self, live: discovery.LiveInterface) -> str | None:
        """Return why another tool is using `live`'s radio, or None if it is free.

        In use means: a mode Core never sets (e.g. AP), a wpa_supplicant or
        hostapd Core did not start bound to it, or a program capturing on a
        monitor netdev of the same radio that Core did not create (profiler,
        kismet, tcpdump). Managed siblings do not count: lldpd binds a packet
        socket to every managed wlanN (#304). Nor do Core's own wlanpiN
        monitors: capturing there while associating on wlanN is normal use.
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
            and other.type == "monitor"
            # Any wlanpi<digits> is Core's: its index can lag the phy's (#365).
            and not (
                other.name.startswith(MONITOR_IFACE_PREFIX)
                and other.name.removeprefix(MONITOR_IFACE_PREFIX).isdigit()
            )
            and not self._is_owned(other)
        ]
        if siblings:
            capturing = usage.capturing_links(live.netns)
            for other in siblings:
                if other.ifindex in capturing:
                    return (
                        f"{other.name} on the same radio (phy{live.phy_index}) "
                        "is in use (a program is capturing on it)"
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
                    # Recreated by someone else: not Core's, so leave its /etc alone.
                    marker.unlink(missing_ok=True)
            else:
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

    def _return_namespace_phys(self, namespace: str) -> list[str]:
        """Stop Core's supplicants in `namespace`, move its phys to root, and return them."""
        self.log.info(f"Returning phys in namespace {namespace} to root")
        wpa_supplicant.stop_namespace_supplicants(namespace)
        stop_namespace_dhcp(namespace)
        try:
            phys = phy.list_phys(namespace=namespace)
        except RunCommandError as e:
            self.log.warning(f"Could not list phys in {namespace}: {e}")
            return []
        moved: list[str] = []
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
            moved.append(phy_name)
            # Core's netdevs travel home with the phy and are handed back.
            for live in travelling:
                self._release(live.name, namespace)
        return moved

    def left_alone(self, in_use: set[str]) -> list[dict[str, Any]]:
        """Report namespaces holding radios that Core has not cleaned up.

        A namespace Core created that is still present (and not used by the
        active configuration) is listed, as is any other namespace that holds
        wireless phys or interfaces. Other namespaces are not Core's concern.
        """
        core = set(self.core_namespaces())
        try:
            names = ns_namespace.list_namespaces()
        except ns_namespace.NetworkNamespaceError as e:
            self.log.warning(f"Failed to list namespaces: {e}")
            return []
        inventory = discovery.list_interfaces_all_namespaces()
        found: list[dict[str, Any]] = []
        for name in names:
            if name in in_use:
                continue
            try:
                validate_namespace_name(name)
            except ValueError:
                found.append({"namespace": name, "reason": "Name Core cannot manage"})
                continue
            try:
                phys = phy.list_phys(namespace=name)
            except RunCommandError:
                phys = []
            ifaces = [live.name for live in inventory if live.netns == name]
            if name in core:
                reason = "Created by Core and not removed"
            elif phys or ifaces:
                reason = "Not created by Core; holds wireless radios"
            else:
                continue
            found.append(
                {
                    "namespace": name,
                    "interfaces": ifaces,
                    "phys": phys,
                    "core_created": name in core,
                    "reason": reason,
                }
            )
        return found

    def reset_namespace(self, namespace: str) -> dict[str, Any]:
        """Return every phy in `namespace` to root and delete it once empty.

        Only on an explicit request naming this namespace: it may belong to
        another tool. Processes running inside it are not killed.
        """
        owned = namespace in self.core_namespaces()
        moved = self._return_namespace_phys(namespace)
        self.stop_app_in_namespace(namespace)
        try:
            remaining = phy.list_phys(
                namespace=namespace
            ) + ns_interfaces.get_interfaces_in_namespace(
                namespace, include_loopback=False
            )
        except RunCommandError as e:
            return {"namespace": namespace, "phys_returned": moved, "detail": str(e)}
        deleted = False
        if not remaining:
            ns_namespace.delete_namespace(namespace, raise_on_fail=False)
            deleted = not ns_namespace.namespace_exists(namespace)
            if deleted and owned:
                self._namespace_marker(namespace).unlink(missing_ok=True)
                self._remove_netns_etc(namespace)
        return {
            "namespace": namespace,
            "phys_returned": moved,
            "deleted": deleted,
            "remaining": remaining,
        }

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
        """Start an application in a namespace or root namespace."""
        apps.start_app_in_namespace(namespace, app_id, pid_dir=self.pid_dir)

    def stop_app_in_namespace(self, namespace: str | None) -> None:
        """Stop an application running in a namespace or root namespace."""
        apps.stop_app_in_namespace(namespace, pid_dir=self.pid_dir)

    def get_status(self, iface: str, namespace: str | None) -> dict[str, Any]:
        """Get network status for an interface."""
        return wpa_status.get_wpa_status(iface, namespace)

    def _find_live(
        self, cfg: NamespaceConfig | RootConfig
    ) -> discovery.LiveInterface | None:
        """Find the live netdev backing cfg, in root, Core's namespaces, or cfg's own.

        `interface` is looked up first. `iface_display_name` (Core's rename) is
        tried only in cfg's namespace: other entries or radios may carry it elsewhere.
        """
        namespace = cfg.namespace if isinstance(cfg, NamespaceConfig) else None
        # Radios in others' namespaces are treated as unplugged, never taken.
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
            # The create may have failed because another radio owns `new_name`.
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
        """Recreate cfg's interface in root on its live phy, restoring the original on failure."""
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
        """Move cfg's live phy into cfg.namespace and recreate the interface there.

        The netdev is deleted before the phy moves so its old name and mode do not
        travel. On failure the original is restored and a namespace created here removed.
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
                # Identity, not name: another tool may reuse the name later.
                marker = self._namespace_marker(namespace)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(self._netns_id(namespace) or "")
                # `ip netns exec` bind-mounts this over /etc/resolv.conf; emptied so a reused name inherits no DNS.
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

    def _safe_unlink(self, path: Path) -> None:
        if path.exists():
            path.unlink()

    def kill_all_supplicants(self) -> None:
        """Stop every wpa_supplicant Core started, across namespaces."""
        wpa_supplicant.kill_all_supplicants()
