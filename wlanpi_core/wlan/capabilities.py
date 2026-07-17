"""Wi-Fi PHY capability queries."""
from __future__ import annotations

from typing import Any

from wlanpi_core.adapters.phy import list_phys
from wlanpi_core.constants import IW_FILE
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.utils.general import run_command


def get_wifi_capabilities() -> dict[str, Any]:
    """Return ``iw phy <n> info`` output for each PHY in root namespace."""
    try:
        phys = list_phys(namespace=None)
    except RunCommandError as exc:
        raise ValidationError(
            f"Unable to list wireless PHY devices: {exc}", status_code=503
        ) from exc

    adapters: list[dict[str, Any]] = []
    for phy in phys:
        try:
            raw = run_command([IW_FILE, "phy", phy, "info"], raise_on_fail=True).stdout
        except RunCommandError as exc:
            adapters.append({"phy": phy, "error": str(exc)})
            continue
        adapters.append({"phy": phy, "info": raw})

    return {"adapters": adapters}
