"""
Network management utilities for DHCP and routing.

This module provides functions for managing DHCP clients and network routes
in namespaces.
"""
import logging
import time
from pathlib import Path
from typing import Optional

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def write_dhcp_config(iface: str, dhcp_dir: Path) -> None:
    """
    Write DHCP configuration file for an interface.

    Args:
        iface: Interface name
        dhcp_dir: Directory for DHCP configuration files

    Examples:
        >>> write_dhcp_config("wlan0", Path("/etc/network/interfaces.d"))
    """
    dhcp_dir.mkdir(parents=True, exist_ok=True)
    dhcp_path = dhcp_dir / f"{iface}.cfg"
    dhcp_path.write_text(f"allow-hotplug {iface}\niface {iface} inet dhcp\n")
    log.debug(f"Wrote DHCP config to {dhcp_path}")


def restart_dhcp_with_timeout(
    iface: str,
    namespace: Optional[str],
    timeout: int = 15,
) -> None:
    """
    Restart DHCP client for an interface with timeout.

    Args:
        iface: Interface name
        namespace: Network namespace name, or None for root
        timeout: Timeout in seconds

    Examples:
        >>> restart_dhcp_with_timeout("wlan0", "test_ns", timeout=15)
    """
    namespace_display = namespace if namespace else "root"
    log.info(f"Starting DHCP client for {iface} in namespace {namespace_display} with timeout {timeout}s")

    try:
        # Clean up existing DHCP clients
        try:
            ns_exec(["dhclient", "-r", iface], namespace=namespace)
        except RunCommandError:
            pass  # May not exist

        try:
            ns_exec(["pkill", "-f", f"dhclient.*{iface}"], namespace=namespace)
        except RunCommandError:
            pass  # May not exist

        time.sleep(1)

        # Use timeout command to limit dhclient execution
        dhcp_cmd = ["timeout", str(timeout), "dhclient", "-v", "-1", iface]

        try:
            ns_exec(dhcp_cmd, namespace=namespace)
            log.info(f"DHCP completed for {iface} in namespace {namespace_display}")
        except RunCommandError as e:
            if "timeout" in str(e).lower() or "124" in str(e):
                log.info(f"DHCP timed out for {iface} in namespace {namespace_display} - trying alternative config")
            else:
                log.warning(f"DHCP failed for {iface} in namespace {namespace_display}: {e}")

    except Exception as e:
        log.warning(f"DHCP setup had issues for {iface} in namespace {namespace_display}: {e}")


def set_default_route(
    iface: str,
    namespace: Optional[str],
    metric: int = 200,
) -> None:
    """
    Set default route for an interface in a namespace.

    Args:
        iface: Interface name
        namespace: Network namespace name, or None for root
        metric: Route metric (default: 200)

    Examples:
        >>> set_default_route("wlan0", "test_ns", metric=200)
    """
    namespace_display = namespace if namespace else "root"
    log.debug(f"Setting default route for {iface} in namespace {namespace_display}")

    try:
        out = ns_exec(["ip", "route", "show", "default"], namespace=namespace).stdout
    except RunCommandError as e:
        # Treat missing FIB table as no default route yet
        if "FIB table does not exist" in str(e):
            out = ""
        else:
            raise

    if iface not in out:
        try:
            ns_exec(
                [
                    "ip",
                    "route",
                    "replace",
                    "default",
                    "dev",
                    iface,
                    "metric",
                    str(metric),
                ],
                namespace=namespace,
            )
            log.info(f"Set default route for {iface} in namespace {namespace_display}")
        except RunCommandError as e:
            # Log and continue; route setup shouldn't fail activation
            log.warning(f"Could not set default route for {iface} in namespace {namespace_display}: {e}")
    else:
        log.debug(f"Default route already set for {iface} in namespace {namespace_display}")
