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
from wlanpi_core.models.network_config_errors import ConfigMalformedError
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services.platform_cache import resolve_model
from wlanpi_core.services.system_service import service_allowlist_key
from wlanpi_core.utils import network_config


def refusal_detail(model: str) -> str | None:
    """Return the 403 detail, or None when this model may transmit."""
    if is_go_token(model):
        return GO_DETAIL
    if model in TRANSMIT_ALLOWED_MODELS:
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


def _config_transmits(cfg_id: str) -> bool:
    try:
        cfg = network_config.get_config(cfg_id)
    except (FileNotFoundError, ConfigMalformedError, ValidationError):
        return False
    entries = [*(cfg.roots or []), *(cfg.namespaces or [])]
    return any(entry.security or entry.autostart_app for entry in entries)


def require_transmit_for_activate(
    id: str,
    _: Annotated[Caller, Depends(verify_auth_wrapper)],
) -> None:
    """Refuse activation of a config that starts a supplicant or an app."""
    try:
        require_wlan_management_enabled()
    except ValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.error_msg) from None
    if _config_transmits(id):
        _refuse_cached_model()
