"""
Connection monitoring for network interfaces.

This module provides background monitoring of network connections,
handling DHCP, default routes, and app startup when connections complete.
"""
import logging
import threading
import time
from typing import Dict, Optional, Union

from wlanpi_core.schemas.network.network import NamespaceConfig, RootConfig
from wlanpi_core.utils.network_management import (
    restart_dhcp_with_timeout,
    set_default_route,
)
from wlanpi_core.wpa.status import get_wpa_status

log = logging.getLogger(__name__)

# Global monitor tracking
_connection_monitors: Dict[str, threading.Thread] = {}
_monitor_stop_flags: Dict[str, threading.Event] = {}
_monitor_lock = threading.Lock()


class ConnectionMonitor:
    """
    Connection monitor for tracking network connection status.

    This class manages background threads that monitor network connections
    and trigger actions (DHCP, routes, apps) when connections complete.
    """

    @staticmethod
    def start_monitor(
        cfg: Union[NamespaceConfig, RootConfig],
        iface: str,
        namespace: Optional[str],
        timeout: int = 15,
    ) -> None:
        """
        Start a background connection monitor for an interface.

        Args:
            cfg: Network configuration
            iface: Interface name
            namespace: Network namespace name, or None for root
            timeout: Monitor timeout in seconds

        Examples:
            >>> ConnectionMonitor.start_monitor(config, "wlan0", "test_ns", timeout=15)
        """
        namespace_display = namespace if namespace else "root"
        monitor_key = f"{namespace_display}:{iface}"

        def monitor_loop():
            try:
                _monitor_body()
            finally:
                # Deregister only after ALL side effects (dhcp, route, app
                # start) have run, and on every exit path, so stop helpers
                # and tests observe a live thread until it is truly done.
                with _monitor_lock:
                    _connection_monitors.pop(monitor_key, None)
                    _monitor_stop_flags.pop(monitor_key, None)

        def _monitor_body():
            log.info(
                f"[ConnectionMonitor] Starting connection monitor for {iface} in {namespace_display} "
                f"(timeout={timeout}s)"
            )
            start = time.time()
            poll_interval = 1
            connected_state = False
            poll_count = 0

            stop_event = _monitor_stop_flags.get(monitor_key)
            if not stop_event:
                log.error(f"[ConnectionMonitor] No stop event found for {monitor_key}, monitor cannot start")
                return

            log.info(
                f"[ConnectionMonitor] Monitor loop started for {iface} in {namespace_display}, "
                f"beginning status checks..."
            )

            while time.time() - start < timeout:
                # Check if we should stop
                if stop_event.is_set():
                    log.info(
                        f"[ConnectionMonitor] Connection monitor for {iface} in {namespace_display} "
                        f"stopped by stop event"
                    )
                    return

                try:
                    status = get_wpa_status(iface, namespace)
                    wpa: dict = status.get("wpa_status", {})
                    wpa_state = (wpa.get("wpa_state") or "").upper()
                    poll_count += 1

                    # Log status every 3 polls (every ~3 seconds)
                    if poll_count % 3 == 0:
                        elapsed = int(time.time() - start)
                        log.info(
                            f"[ConnectionMonitor] Status check #{poll_count} for {iface} in {namespace_display}: "
                            f"wpa_state={wpa_state}, elapsed={elapsed}s/{timeout}s"
                        )

                    if wpa_state == "COMPLETED":
                        connected_state = True
                        elapsed = int(time.time() - start)
                        log.info(
                            f"[ConnectionMonitor] Connection completed for {iface} in {namespace_display} "
                            f"after {elapsed}s ({poll_count} status checks)"
                        )
                        break

                    time.sleep(poll_interval)
                except Exception as e:
                    log.warning(
                        f"[ConnectionMonitor] Error checking connection status for {iface}: {e}",
                        exc_info=True,
                    )
                    time.sleep(poll_interval)

            if connected_state:
                # Start DHCP after connection
                try:
                    log.info(f"[ConnectionMonitor] Starting DHCP for {iface} in {namespace_display} after connection")
                    restart_dhcp_with_timeout(iface, namespace, timeout=15)

                    # Set default route if requested
                    if cfg.default_route:
                        log.info(f"[ConnectionMonitor] Setting default route for {iface} in {namespace_display}")
                        set_default_route(iface, namespace)

                    # Start app if configured
                    if cfg.autostart_app:
                        log.info(
                            f"[ConnectionMonitor] Starting autostart app '{cfg.autostart_app}' "
                            f"for {iface} in {namespace_display}"
                        )
                        from wlanpi_core.namespaces.apps import start_app_in_namespace
                        start_app_in_namespace(namespace, cfg.autostart_app)

                    log.info(f"[ConnectionMonitor] Connection setup complete for {iface} in {namespace_display}")
                except Exception as e:
                    log.error(
                        f"[ConnectionMonitor] Error completing connection setup for {iface}: {e}",
                        exc_info=True,
                    )
            else:
                # Not connected within timeout
                elapsed = int(time.time() - start)
                log.info(
                    f"[ConnectionMonitor] Did not reach connected state within {timeout}s for {iface} "
                    f"in {namespace_display} (elapsed={elapsed}s, checks={poll_count}). "
                    f"Configuration remains active for future connection."
                )

        # Create and start monitor thread
        log.info(
            f"[ConnectionMonitor] Creating monitor thread for {iface} in {namespace_display} "
            f"(monitor_key={monitor_key})"
        )
        stop_event = threading.Event()
        monitor_thread = threading.Thread(
            target=monitor_loop,
            name=f"ConnectionMonitor-{monitor_key}",
            daemon=True,
        )

        with _monitor_lock:
            _connection_monitors[monitor_key] = monitor_thread
            _monitor_stop_flags[monitor_key] = stop_event

        try:
            monitor_thread.start()
            log.info(
                f"[ConnectionMonitor] Connection monitor thread started successfully for {iface} "
                f"in {namespace_display} (thread={monitor_thread.name}, daemon={monitor_thread.daemon}, "
                f"alive={monitor_thread.is_alive()})"
            )
        except Exception as e:
            log.error(
                f"[ConnectionMonitor] Failed to start monitor thread for {iface} in {namespace_display}: {e}",
                exc_info=True,
            )
            # Clean up on failure
            with _monitor_lock:
                _connection_monitors.pop(monitor_key, None)
                _monitor_stop_flags.pop(monitor_key, None)


def stop_connection_monitor(namespace: Optional[str], iface: str) -> None:
    """
    Stop a connection monitor for a specific interface/namespace.

    Args:
        namespace: Network namespace name, or None for root
        iface: Interface name

    Examples:
        >>> stop_connection_monitor("test_ns", "wlan0")
    """
    namespace_display = namespace if namespace else "root"
    monitor_key = f"{namespace_display}:{iface}"

    with _monitor_lock:
        stop_event = _monitor_stop_flags.get(monitor_key)
        monitor_thread = _connection_monitors.get(monitor_key)
        if stop_event:
            stop_event.set()

    # Join OUTSIDE the lock: the monitor thread's own deregistration needs
    # _monitor_lock, so joining while holding it guarantees a timeout.
    if monitor_thread and monitor_thread.is_alive():
        monitor_thread.join(timeout=2.0)

    with _monitor_lock:
        _connection_monitors.pop(monitor_key, None)
        _monitor_stop_flags.pop(monitor_key, None)

    log.info(f"Stopped connection monitor for {iface} in {namespace_display}")


def stop_all_connection_monitors() -> None:
    """
    Stop all active connection monitors. Useful for shutdown or cleanup.

    Examples:
        >>> stop_all_connection_monitors()
    """
    with _monitor_lock:
        # Signal all monitors to stop
        for stop_event in _monitor_stop_flags.values():
            stop_event.set()
        threads = list(_connection_monitors.items())

    # Join OUTSIDE the lock: each monitor thread's own deregistration needs
    # _monitor_lock, so joining while holding it guarantees a timeout.
    for monitor_key, monitor_thread in threads:
        if monitor_thread.is_alive():
            monitor_thread.join(timeout=2.0)
            if monitor_thread.is_alive():
                log.warning(f"Connection monitor {monitor_key} did not stop within timeout")

    with _monitor_lock:
        _connection_monitors.clear()
        _monitor_stop_flags.clear()

    log.info("All connection monitors stopped")
