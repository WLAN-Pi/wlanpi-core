"""DHCP lease read and interface renew."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.utils.general import run_command_async
from wlanpi_core.utils.validation import validate_interface_name

log = logging.getLogger(__name__)

DHCP_LEASE_DIR = Path("/var/lib/dhcp")
_DHCP_LEASE_FILE_GLOB = "dhclient*.leases"
_NETWORKCTL = "/usr/bin/networkctl"
_NETWORKCTL_STATUS_TIMEOUT_SEC = 5


async def renew_interface_dhcp(iface: str, timeout: int = 15) -> dict[str, Any]:
    """Renew DHCP only when ``iface`` is managed by systemd-networkd."""
    try:
        iface = validate_interface_name(iface)
    except ValueError as error:
        raise ValidationError("invalid interface name", status_code=400)

    status_result = await run_command_async(
        [_NETWORKCTL, "status", iface, "--json=short", "--no-pager"],
        raise_on_fail=False,
        timeout=min(timeout, _NETWORKCTL_STATUS_TIMEOUT_SEC),
    )
    if not status_result.success:
        raise ValidationError(
            f"interface {iface} is not managed by systemd-networkd",
            status_code=409,
        )

    try:
        status = json.loads(status_result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("networkctl returned invalid interface status") from exc

    if (
        status.get("Name") != iface
        or status.get("AdministrativeState") == "unmanaged"
        or not status.get("NetworkFile")
    ):
        raise ValidationError(
            f"interface {iface} is not managed by systemd-networkd",
            status_code=409,
        )

    log.info("Renewing DHCP lease for networkd-managed interface %s", iface)
    await run_command_async(
        [_NETWORKCTL, "renew", iface],
        raise_on_fail=True,
        timeout=timeout,
    )
    return {
        "interface": iface,
        "namespace": None,
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
