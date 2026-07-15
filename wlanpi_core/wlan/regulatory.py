"""Wi-Fi regulatory domain queries."""
from __future__ import annotations

from typing import Any

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import system_service
from wlanpi_core.utils.general import run_command


def get_wifi_regulatory() -> dict[str, Any]:
    """Return structured reg-domain info plus raw ``iw reg get`` output."""
    summary = system_service.get_reg_domain()
    raw = summary.get("raw") if summary.get("source") == "iw" else None
    if not raw:
        try:
            raw = run_command(["iw", "reg", "get"], raise_on_fail=True).stdout.strip()
        except (RunCommandError, FileNotFoundError) as exc:
            raise ValidationError(
                f"Unable to read regulatory domain: {exc}", status_code=503
            ) from exc

    return {
        "country": summary.get("country"),
        "source": summary.get("source"),
        "raw": raw,
    }
