"""List, move, and bring up or down interfaces in network namespaces."""

import logging

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)


def get_interfaces_in_namespace(
    namespace: str, include_loopback: bool = False
) -> list[str]:
    """Return interface names in namespace, without loopback unless include_loopback."""
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.debug(f"Getting interfaces in namespace: {namespace}")

    try:
        result = ns_exec(
            ["ip", "-o", "link", "show"], namespace=namespace, no_output=True
        )
        interfaces = []

        for line in result.stdout.splitlines():
            if not line.strip():
                continue

            # Format: '1: lo: <LOOPBACK,UP,LOWER_UP> ...'
            parts = line.split(":", 2)
            if len(parts) >= 2:
                iface_name = parts[1].strip()
                if include_loopback or not iface_name.startswith("lo"):
                    interfaces.append(iface_name)

        log.debug(f"Found {len(interfaces)} interfaces in namespace {namespace}")
        return interfaces
    except RunCommandError as e:
        log.error(f"Failed to get interfaces in namespace {namespace}: {e}")
        raise


def move_interface_to_namespace(
    interface: str,
    namespace: str,
    interface_type: str | None = None,
) -> bool:
    """Move the interface link from root into namespace; return True or raise RunCommandError."""
    if not interface or not interface.strip():
        raise ValueError("interface cannot be empty")
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.info(f"Moving interface {interface} to namespace {namespace}")

    try:
        ns_exec(
            ["ip", "link", "set", interface, "netns", namespace],
            namespace=None,
        )
        log.info(f"Successfully moved interface {interface} to namespace {namespace}")
        return True
    except RunCommandError as e:
        log.error(f"Failed to move interface {interface} to namespace {namespace}: {e}")
        raise


def move_interface_to_root(interface: str, namespace: str) -> bool:
    """Move the interface from namespace back to root; return True or raise RunCommandError."""
    if not interface or not interface.strip():
        raise ValueError("interface cannot be empty")
    if not namespace or not namespace.strip():
        raise ValueError("namespace cannot be empty")

    log.info(f"Moving interface {interface} from namespace {namespace} to root")

    try:
        # netns 1 is PID 1's namespace: root.
        ns_exec(
            ["ip", "link", "set", interface, "netns", "1"],
            namespace=namespace,
        )

        log.info(f"Successfully moved interface {interface} to root namespace")
        return True
    except RunCommandError as e:
        log.error(
            f"Failed to move interface {interface} from namespace {namespace} to root: {e}"
        )
        raise


def bring_interface_up(interface: str, namespace: str | None = None) -> bool:
    """Bring the interface up in namespace (None for root); return True or raise RunCommandError."""
    if not interface or not interface.strip():
        raise ValueError("interface cannot be empty")

    log.debug(f"Bringing interface {interface} up in namespace {namespace or 'root'}")

    try:
        ns_exec(["ip", "link", "set", interface, "up"], namespace=namespace)
        log.debug(f"Interface {interface} brought up successfully")
        return True
    except RunCommandError as e:
        log.error(f"Failed to bring interface {interface} up: {e}")
        raise


def bring_interface_down(interface: str, namespace: str | None = None) -> bool:
    """Bring the interface down in namespace (None for root); return True or raise RunCommandError."""
    if not interface or not interface.strip():
        raise ValueError("interface cannot be empty")

    log.debug(f"Bringing interface {interface} down in namespace {namespace or 'root'}")

    try:
        ns_exec(["ip", "link", "set", interface, "down"], namespace=namespace)
        log.debug(f"Interface {interface} brought down successfully")
        return True
    except RunCommandError as e:
        log.error(f"Failed to bring interface {interface} down: {e}")
        raise
