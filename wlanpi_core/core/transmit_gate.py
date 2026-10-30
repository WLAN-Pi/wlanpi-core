"""HTTP dependencies that refuse transmit on a Go or an unknown model."""

from typing import Annotated

from fastapi import Depends, HTTPException

from wlanpi_core.core.auth import Caller, verify_auth_wrapper
from wlanpi_core.core.transmit_policy import TRANSMIT_UNITS, refusal_detail
from wlanpi_core.services.platform_cache import resolve_model
from wlanpi_core.services.system_service import service_allowlist_key


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
