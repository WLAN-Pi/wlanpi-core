"""Device mode checks for mode-specific API endpoints."""

from __future__ import annotations

from wlanpi_core.core.config import settings
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services.system_service import get_mode


def require_mode(*allowed: str) -> str:
    """
    Return the current device mode if it is one of ``allowed``.

    Raises:
        ValidationError: HTTP 409 when the current mode is not permitted.
    """
    current = get_mode()
    if current not in allowed:
        allowed_label = " or ".join(allowed)
        raise ValidationError(
            f"This endpoint requires device mode {allowed_label}; current mode is {current}",
            status_code=409,
        )
    return current


def require_wlan_management_enabled() -> None:
    """Raise HTTP 409 when WLAN_MANAGEMENT is manual: the operator owns Wi-Fi interfaces."""
    if settings.WLAN_MANAGEMENT == "manual":
        raise ValidationError(
            "wlanpi-core Wi-Fi management is disabled (WLAN_MANAGEMENT=manual)",
            status_code=409,
        )
