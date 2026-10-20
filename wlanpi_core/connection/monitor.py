"""Background monitors that finish DHCP, route and app setup once a connection completes."""

import logging
import threading
import time
from typing import Any

from wlanpi_core.schemas.network.network import NamespaceConfig, RootConfig
from wlanpi_core.utils.network_management import (
    restart_dhcp_with_timeout,
    set_default_route,
)
from wlanpi_core.wpa.status import get_wpa_status

log = logging.getLogger(__name__)

_connection_monitors: dict[str, threading.Thread] = {}
_monitor_stop_flags: dict[str, threading.Event] = {}
_monitor_lock = threading.Lock()


class ConnectionMonitor:
    """Start background threads that complete setup once an interface connects."""

    @staticmethod
    def start_monitor(
        cfg: NamespaceConfig | RootConfig,
        iface: str,
        namespace: str | None,
        timeout: int = 15,
    ) -> None:
        """Start a monitor for `iface` in `namespace` (None for root), waiting `timeout` seconds."""
        namespace_display = namespace if namespace else "root"
        monitor_key = f"{namespace_display}:{iface}"

        # An older monitor would run DHCP or start an app for a superseded config.
        stop_connection_monitor(namespace, iface)

        # Captured, not looked up by key, so a newer monitor cannot swap it.
        stop_event = threading.Event()

        def monitor_loop() -> None:
            try:
                _monitor_body()
            finally:
                # Deregister last so a join waits for every side effect.
                with _monitor_lock:
                    if _connection_monitors.get(monitor_key) is monitor_thread:
                        _connection_monitors.pop(monitor_key, None)
                    if _monitor_stop_flags.get(monitor_key) is stop_event:
                        _monitor_stop_flags.pop(monitor_key, None)

        def _monitor_body() -> None:
            log.info(
                f"[ConnectionMonitor] Starting connection monitor for {iface} in {namespace_display} "
                f"(timeout={timeout}s)"
            )
            start = time.time()
            poll_interval = 1
            connected_state = False
            poll_count = 0

            log.info(
                f"[ConnectionMonitor] Monitor loop started for {iface} in {namespace_display}, "
                f"beginning status checks..."
            )

            while time.time() - start < timeout:
                if stop_event.is_set():
                    log.info(
                        f"[ConnectionMonitor] Connection monitor for {iface} in {namespace_display} "
                        f"stopped by stop event"
                    )
                    return

                try:
                    status = get_wpa_status(iface, namespace)
                    wpa: dict[str, Any] = status.get("wpa_status", {})
                    wpa_state = (wpa.get("wpa_state") or "").upper()
                    poll_count += 1

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
                # A stop can land mid-poll; recheck before each side effect.
                if stop_event.is_set():
                    log.info(f"[ConnectionMonitor] {monitor_key} stopped before DHCP")
                    return
                try:
                    log.info(
                        f"[ConnectionMonitor] Starting DHCP for {iface} in {namespace_display} after connection"
                    )
                    restart_dhcp_with_timeout(
                        iface, namespace, timeout=15, default_route=cfg.default_route
                    )
                    if stop_event.is_set():
                        log.info(
                            f"[ConnectionMonitor] {monitor_key} stopped after DHCP; skipping route and app"
                        )
                        return

                    if cfg.default_route:
                        log.info(
                            f"[ConnectionMonitor] Setting default route for {iface} in {namespace_display}"
                        )
                        set_default_route(iface, namespace)

                    if cfg.autostart_app and not stop_event.is_set():
                        log.info(
                            f"[ConnectionMonitor] Starting autostart app '{cfg.autostart_app}' "
                            f"for {iface} in {namespace_display}"
                        )
                        from wlanpi_core.namespaces.apps import start_app_in_namespace

                        start_app_in_namespace(namespace, cfg.autostart_app)

                    log.info(
                        f"[ConnectionMonitor] Connection setup complete for {iface} in {namespace_display}"
                    )
                except Exception as e:
                    log.error(
                        f"[ConnectionMonitor] Error completing connection setup for {iface}: {e}",
                        exc_info=True,
                    )
            else:
                elapsed = int(time.time() - start)
                log.info(
                    f"[ConnectionMonitor] Did not reach connected state within {timeout}s for {iface} "
                    f"in {namespace_display} (elapsed={elapsed}s, checks={poll_count}). "
                    f"Configuration remains active for future connection."
                )
                if stop_event.is_set():
                    return
                # dhcpcd leases on a late association; Wi-Fi 7 tri-band scans can outlast `timeout`.
                try:
                    restart_dhcp_with_timeout(
                        iface, namespace, timeout=1, default_route=cfg.default_route
                    )
                except Exception as e:
                    log.warning(
                        f"[ConnectionMonitor] Could not leave DHCP running for {iface}: {e}"
                    )

        log.info(
            f"[ConnectionMonitor] Creating monitor thread for {iface} in {namespace_display} "
            f"(monitor_key={monitor_key})"
        )
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
            with _monitor_lock:
                _connection_monitors.pop(monitor_key, None)
                _monitor_stop_flags.pop(monitor_key, None)


def stop_connection_monitor(namespace: str | None, iface: str) -> None:
    """Stop the connection monitor for `iface` in `namespace` (None for root)."""
    namespace_display = namespace if namespace else "root"
    monitor_key = f"{namespace_display}:{iface}"

    with _monitor_lock:
        stop_event = _monitor_stop_flags.get(monitor_key)
        monitor_thread = _connection_monitors.get(monitor_key)
        if stop_event:
            stop_event.set()

    # Join outside the lock: the thread's deregistration takes _monitor_lock.
    if monitor_thread and monitor_thread.is_alive():
        monitor_thread.join(timeout=2.0)

    with _monitor_lock:
        _connection_monitors.pop(monitor_key, None)
        _monitor_stop_flags.pop(monitor_key, None)

    log.info(f"Stopped connection monitor for {iface} in {namespace_display}")


def stop_all_connection_monitors() -> None:
    """Stop all active connection monitors."""
    with _monitor_lock:
        for stop_event in _monitor_stop_flags.values():
            stop_event.set()
        threads = list(_connection_monitors.items())

    # Join outside the lock: each thread's deregistration takes _monitor_lock.
    for monitor_key, monitor_thread in threads:
        if monitor_thread.is_alive():
            monitor_thread.join(timeout=2.0)
            if monitor_thread.is_alive():
                log.warning(
                    f"Connection monitor {monitor_key} did not stop within timeout"
                )

    with _monitor_lock:
        _connection_monitors.clear()
        _monitor_stop_flags.clear()

    log.info("All connection monitors stopped")
