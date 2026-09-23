"""
Network management utilities for DHCP and routing.

This module provides functions for managing DHCP clients and network routes
in namespaces.
"""

import logging
import os
import shutil
import signal
import time
from pathlib import Path

from wlanpi_core.constants import RUN_DIR
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


# Directory name for the root namespace; `@` cannot appear in a netns name.
_ROOT_DIR_NAME = "@root"

# dhcpcd keeps its pidfile, control socket and leases under fixed paths
# (/run/dhcpcd, /var/lib/dhcpcd) that every netns shares, so a second dhcpcd
# for the same interface name in another namespace just talks to the first.
# Run each one in a private mount namespace with its own copies of both.
# /run/dhcpcd is tmpfs and absent until something runs dhcpcd, so create the
# mount points first or the bind fails on a freshly booted device.
_DHCPCD_WRAPPER = (
    "mkdir -p /run/dhcpcd /var/lib/dhcpcd "
    '&& mount --bind "$1" /run/dhcpcd && mount --bind "$2" /var/lib/dhcpcd '
    '&& shift 2 && exec dhcpcd "$@"'
)


def dhcp_dir(iface: str, namespace: str | None) -> Path:
    """Return the private dhcpcd state directory for (namespace, iface)."""
    return Path(RUN_DIR) / "dhcpcd" / (namespace or _ROOT_DIR_NAME) / iface


def _read_cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [arg.decode(errors="replace") for arg in raw.split(b"\0") if arg]


def _stop_dhcpcd_dir(state: Path) -> bool:
    """Release and stop the dhcpcd whose private state is `state`.

    Returns:
        False if that dhcpcd is still running afterwards
    """
    iface = state.name
    pidfile = state / "run" / f"{iface}-4.pid"
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return True
    argv = _read_cmdline(pid)
    # dhcpcd rewrites its title to "dhcpcd: <iface> [ip4]"; match the name
    # exactly, so a reused PID running dhcpcd for wlan10 is not taken for wlan1.
    title = " ".join(argv)
    if not argv or not (title.startswith(f"dhcpcd: {iface} ") or iface in argv[1:]):
        return True
    try:
        # SIGALRM: release the lease and exit. (SIGHUP only rebinds in
        # dhcpcd 10, leaving it running.)
        os.kill(pid, signal.SIGALRM)
    except ProcessLookupError:
        return True
    for _ in range(30):
        if not _read_cmdline(pid):
            return True
        time.sleep(0.1)
    log.warning(f"dhcpcd {pid} for {iface} did not exit after SIGALRM")
    return False


def _remove_dhcpcd_dir(state: Path) -> None:
    # The lease file is named after the SSID; don't leave it behind.
    shutil.rmtree(state, ignore_errors=True)
    try:
        state.parent.rmdir()
    except OSError:
        pass  # other interfaces' state remains


def stop_dhcp(iface: str, namespace: str | None) -> None:
    """Release the lease and stop the dhcpcd Core started for (namespace, iface).

    Its private state directory is removed once it has exited.
    """
    state = dhcp_dir(iface, namespace)
    if _stop_dhcpcd_dir(state):
        _remove_dhcpcd_dir(state)


def stop_namespace_dhcp(namespace: str) -> None:
    """Stop every dhcpcd Core started in `namespace`, removing its state."""
    for state in sorted(dhcp_dir("x", namespace).parent.glob("*")):
        if _stop_dhcpcd_dir(state):
            _remove_dhcpcd_dir(state)


def restart_dhcp_with_timeout(
    iface: str,
    namespace: str | None,
    timeout: int = 15,
    default_route: bool = False,
) -> None:
    """
    Restart the DHCP client (dhcpcd) for an interface.

    Waits up to `timeout` seconds for a lease, then leaves dhcpcd running in
    the background to renew or keep trying. No IPv4 link-local fallback, so a
    missing DHCP server never produces a 169.254 address or a gatewayless
    default route. The DHCP router becomes the default route (metric 200)
    only when `default_route` is set. The hostname and timesyncd hooks are
    off; in root the resolv.conf hook is off too (NetworkManager owns DNS),
    while in a namespace it writes /etc/netns/<ns>/resolv.conf.

    Args:
        iface: Interface name
        namespace: Network namespace name, or None for root
        timeout: Seconds to wait for a lease before backgrounding
        default_route: Install a default route via the DHCP router

    Examples:
        >>> restart_dhcp_with_timeout("wlan0", "test_ns", timeout=15)
    """
    namespace_display = namespace if namespace else "root"
    log.info(
        f"Starting DHCP client for {iface} in namespace {namespace_display} with timeout {timeout}s"
    )
    state = dhcp_dir(iface, namespace)
    _stop_dhcpcd_dir(state)  # keep the state: the DUID and lease are reused
    for sub in ("run", "lib"):
        (state / sub).mkdir(mode=0o700, parents=True, exist_ok=True)

    hooks = ["-C", "hostname", "-C", "timesyncd"]
    if namespace is None:
        hooks += ["-C", "resolv.conf"]
    route = ["-m", "200"] if default_route else ["-G"]
    cmd = [
        "unshare",
        "--mount",
        "--propagation",
        "private",
        "sh",
        "-c",
        _DHCPCD_WRAPPER,
        "dhcpcd-wlanpi",
        str(state / "run"),
        str(state / "lib"),
        "-4",
        "-L",
        "-t",
        str(timeout),
        *route,
        *hooks,
        iface,
    ]
    try:
        ns_exec(cmd, namespace=namespace)
        log.info(f"DHCP started for {iface} in namespace {namespace_display}")
    except RunCommandError as e:
        log.warning(f"DHCP failed for {iface} in namespace {namespace_display}: {e}")


def set_default_route(
    iface: str,
    namespace: str | None,
    metric: int = 200,
) -> None:
    """
    Make the DHCP router on `iface` the default route in its namespace.

    Only a route via a gateway is ever installed. If `iface` has no default
    route with a gateway (no lease yet, or no router offered), nothing is
    added: a gatewayless `default dev <iface>` route breaks routing.

    Args:
        iface: Interface name
        namespace: Network namespace name, or None for root
        metric: Route metric (default: 200)

    Examples:
        >>> set_default_route("wlan0", "test_ns", metric=200)
    """
    namespace_display = namespace if namespace else "root"
    try:
        out = ns_exec(
            ["ip", "-4", "route", "show", "default", "dev", iface], namespace=namespace
        ).stdout
    except RunCommandError as e:
        log.warning(f"Could not read routes for {iface} in {namespace_display}: {e}")
        return
    gateway = None
    for line in out.splitlines():
        parts = line.split()
        if parts[:2] == ["default", "via"] and len(parts) > 2:
            gateway = parts[2]
            break
    if gateway is None:
        log.warning(
            f"No gateway on {iface} in {namespace_display}; not adding a default route"
        )
        return
    try:
        ns_exec(
            [
                "ip",
                "route",
                "replace",
                "default",
                "via",
                gateway,
                "dev",
                iface,
                "metric",
                str(metric),
            ],
            namespace=namespace,
        )
        log.info(f"Default route via {gateway} on {iface} in {namespace_display}")
    except RunCommandError as e:
        # Log and continue; route setup shouldn't fail activation
        log.warning(
            f"Could not set default route for {iface} in namespace {namespace_display}: {e}"
        )
