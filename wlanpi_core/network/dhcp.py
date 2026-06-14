"""DHCP lease read and interface renew."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.network.lookup import resolve_interface_namespace
from wlanpi_core.utils.network_management import restart_dhcp_with_timeout

log = logging.getLogger(__name__)

DHCP_LEASE_DIR = Path("/var/lib/dhcp")
_DHCP_LEASE_FILE_GLOB = "dhclient*.leases"


def renew_interface_dhcp(iface: str, timeout: int = 15) -> dict[str, Any]:
    """Renew DHCP on ``iface`` in its current namespace (or root)."""
    iface = iface.strip()
    if not iface:
        raise ValidationError("interface name is required", status_code=400)

    namespace = resolve_interface_namespace(iface)
    log.debug("renew_interface_dhcp iface=%s namespace=%r", iface, namespace)
    restart_dhcp_with_timeout(iface, namespace, timeout=timeout)
    return {
        "interface": iface,
        "namespace": namespace,
        "status": "renewed",
    }


def _parse_lease_blocks(text: str) -> list[dict[str, Any]]:
    leases: list[dict[str, Any]] = []
    for block in re.findall(r"lease\s*\{([^}]*)\}", text, flags=re.DOTALL):
        entry: dict[str, Any] = {}
        for line in block.splitlines():
            line = line.strip().rstrip(";")
            if not line or line.startswith("#"):
                continue
            if line.startswith("option "):
                _, _, remainder = line.partition("option ")
                if " " in remainder:
                    key, value = remainder.split(" ", 1)
                    entry[f"option_{key.replace('-', '_')}"] = value.strip('"')
                continue
            if " " in line:
                key, value = line.split(" ", 1)
                entry[key.replace("-", "_")] = value.strip('"')
        if entry:
            leases.append(entry)
    return leases


def get_dhcp_leases(lease_dir: Path = DHCP_LEASE_DIR) -> dict[str, Any]:
    """Parse dhclient lease files under ``/var/lib/dhcp``."""
    log.debug("get_dhcp_leases dir=%s", lease_dir)
    if not lease_dir.exists():
        return {"leases": [], "source": str(lease_dir), "error": "lease directory not found"}

    all_leases: list[dict[str, Any]] = []
    for path in sorted(lease_dir.glob(_DHCP_LEASE_FILE_GLOB)):
        try:
            text = path.read_text()
        except OSError as exc:
            log.warning("Could not read lease file %s: %r", path, exc)
            continue
        for lease in _parse_lease_blocks(text):
            lease["source_file"] = path.name
            all_leases.append(lease)

    return {"leases": all_leases, "source": str(lease_dir)}
