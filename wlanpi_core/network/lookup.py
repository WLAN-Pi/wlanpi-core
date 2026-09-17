"""Resolve which network namespace owns an interface."""

from __future__ import annotations

import logging
from typing import Optional

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.utils import network_config
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.validation import validate_interface_name

log = logging.getLogger(__name__)


def _exists_in_root(iface: str) -> bool:
    """Return True if ``iface`` exists as a link in the root namespace."""
    result = run_command(["ip", "link", "show", iface], raise_on_fail=False)
    return result.success


def resolve_interface_namespace(iface: str) -> Optional[str]:
    """
    Return the namespace containing ``iface``, or None for root.

    Uses ``network_config.status()`` (same view as ``GET /network/config/status``).
    """
    iface = validate_interface_name(iface)

    try:
        status = network_config.status()
    except Exception as exc:
        log.warning("Could not read namespace status for %s: %r", iface, exc)
        raise ValidationError(
            "Unable to determine the interface namespace",
            status_code=503,
        ) from exc

    if not isinstance(status, dict):
        raise ValidationError(
            "Unable to determine the interface namespace",
            status_code=503,
        )

    root_status = status.get("root") or {}
    if (
        isinstance(root_status, dict)
        and "error" not in root_status
        and iface in root_status
    ):
        return None

    incomplete_status = not isinstance(root_status, dict) or "error" in root_status
    for ns_name, ns_status in status.items():
        if ns_name == "root" or not isinstance(ns_status, dict):
            if ns_name != "root":
                incomplete_status = True
            continue
        if "error" in ns_status:
            incomplete_status = True
            continue
        if iface in ns_status:
            return ns_name

    if incomplete_status:
        raise ValidationError(
            "Unable to determine the interface namespace from incomplete status",
            status_code=503,
        )

    # ``status()`` only reports wireless interfaces (via ``iw dev``), so a real
    # root interface such as ``eth0`` is never listed. If it is not claimed by
    # any namespace, fall back to the root interface list before declaring it
    # missing.
    if _exists_in_root(iface):
        return None

    raise ValidationError(f"Interface {iface} was not found", status_code=404)
