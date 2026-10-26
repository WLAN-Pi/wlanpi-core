"""HTTP dependencies that refuse transmit on a Go or an unknown model."""

from typing import Annotated

from fastapi import Depends, HTTPException

from wlanpi_core.core.auth import Caller, verify_auth_wrapper
from wlanpi_core.core.mode_guard import require_wlan_management_enabled
from wlanpi_core.core.transmit_policy import (
    GO_DETAIL,
    TRANSMIT_ALLOWED_MODELS,
    TRANSMIT_UNITS,
    UNKNOWN_DETAIL,
    is_go_token,
)
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services.platform_cache import ModelToken, resolve_model
from wlanpi_core.services.system_service import service_allowlist_key


def refusal_detail(model: ModelToken) -> str | None:
    """Return the 403 detail, or None when this token may transmit."""
    if is_go_token(model.value):
        return GO_DETAIL
    if model.value in TRANSMIT_ALLOWED_MODELS:
        return None
    return UNKNOWN_DETAIL


def _refuse_cached_model() -> None:
    detail = refusal_detail(resolve_model())
    if detail is not None:
        raise HTTPException(status_code=403, detail=detail)


def require_transmit(
    _: Annotated[Caller, Depends(verify_auth_wrapper)],
) -> None:
    """Refuse the request when the model cannot transmit."""
    _refuse_cached_model()


def require_transmit_for_unit(
    name: str,
    _: Annotated[Caller, Depends(verify_auth_wrapper)],
) -> None:
    """Refuse start or restart when `name` is a transmit-capable unit."""
    if service_allowlist_key(name) in TRANSMIT_UNITS:
        _refuse_cached_model()


def require_transmit_for_power(
    action: str,
    _: Annotated[Caller, Depends(verify_auth_wrapper)],
) -> None:
    """Refuse bluetooth power-on when `action` is `on`."""
    if action == "on":
        _refuse_cached_model()


def require_transmit_for_activate(
    _: Annotated[Caller, Depends(verify_auth_wrapper)],
) -> None:
    """Refuse activation when the model cannot transmit."""
    try:
        require_wlan_management_enabled()
    except ValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.error_msg) from None
    _refuse_cached_model()
