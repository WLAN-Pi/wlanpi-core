"""HTTP dependencies that refuse transmit on a Go or an unknown model."""

from typing import Annotated

from fastapi import Depends, HTTPException

from wlanpi_core.core.auth import Caller, verify_auth_wrapper
from wlanpi_core.core.mode_guard import require_wlan_management_enabled
from wlanpi_core.core.transmit_policy import (
    GO_DETAIL,
    GO_MODEL,
    TRANSMIT_UNITS,
    UNKNOWN_DETAIL,
)
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import platform_cache
from wlanpi_core.services.platform_cache import ModelToken
from wlanpi_core.services.system_service import service_allowlist_key


def refusal_detail(model: ModelToken) -> str | None:
    """Return the 403 detail for `Go` or `Unknown`, else None."""
    if model.value == GO_MODEL:
        return GO_DETAIL
    if model.value == "Unknown":
        return UNKNOWN_DETAIL
    return None


def _refuse_cached_model() -> None:
    detail = refusal_detail(platform_cache.cached_model())
    if detail is not None:
        raise HTTPException(status_code=403, detail=detail)


def require_transmit(
    _: Annotated[Caller, Depends(verify_auth_wrapper)],
) -> None:
    """Refuse the request when the cached model cannot transmit."""
    _refuse_cached_model()


def require_transmit_for_unit(
    name: str,
    _: Annotated[Caller, Depends(verify_auth_wrapper)],
) -> None:
    """Refuse start or restart of a transmit-capable unit.

    The parameter name stays `name`, matching the route.
    """
    if service_allowlist_key(name) in TRANSMIT_UNITS:
        _refuse_cached_model()


def require_transmit_for_power(
    action: str,
    _: Annotated[Caller, Depends(verify_auth_wrapper)],
) -> None:
    """Refuse bluetooth power-on when `action` is `on`.

    The parameter name stays `action`.
    """
    if action == "on":
        _refuse_cached_model()


def require_transmit_for_activate(
    _: Annotated[Caller, Depends(verify_auth_wrapper)],
) -> None:
    """Refuse activation when the cached model cannot transmit.

    Manual WLAN management is reported first, as that check's HTTP status.
    """
    try:
        require_wlan_management_enabled()
    except ValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.error_msg) from None
    _refuse_cached_model()
