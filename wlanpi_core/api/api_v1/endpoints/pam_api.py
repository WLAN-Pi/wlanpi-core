"""Internal PAM authentication endpoint (wlanpi-webui session login).

wlanpi-webui runs as the unprivileged ``wlanpi`` account, which pam_unix cannot
use to verify other local users, so the root-running core brokers the PAM
conversation on its behalf. Authorization for WebUI management access is
enforced by the ``wlanpi-webui`` PAM service (its account stack requires the
``sudo`` group), not by Python code here.

Restricted to localhost HMAC callers only; never invoked with a bearer token.
The password is never stored, logged, or exchanged for a Core token.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from wlanpi_core.core.auth import verify_hmac
from wlanpi_core.core.logging import get_logger
from wlanpi_core.schemas.auth.pam import PAMAuthRequest, PAMAuthResponse

router = APIRouter()

log = get_logger(__name__)

PAM_SERVICE = "wlanpi-webui"

# linux-pam return codes relevant to login (python-pam re-exports these)
PAM_SUCCESS = 0
PAM_NEW_AUTHTOK_REQD = 12
PAM_AUTHTOK_EXPIRED = 27


def _pam_authenticate(username: str, password: str) -> int:
    """Run the blocking PAM conversation in a worker thread."""
    import pam  # lazy: keeps core importable without python-pam installed

    auth = pam.pam()
    auth.authenticate(username, password, service=PAM_SERVICE, resetcreds=False)
    return auth.code


@router.post(
    "/pam",
    response_model=PAMAuthResponse,
    include_in_schema=False,
    dependencies=[Depends(verify_hmac)],
)
async def pam_authenticate(request: Request, body: PAMAuthRequest) -> Any:
    """Verify a local account password against PAM (HMAC-only, localhost)."""
    password = body.password.get_secret_value()

    try:
        code = await asyncio.to_thread(_pam_authenticate, body.username, password)
    except Exception:
        log.exception("PAM authentication failed unexpectedly")
        raise HTTPException(
            status_code=500, detail="Authentication unavailable"
        ) from None

    if code == PAM_SUCCESS:
        return PAMAuthResponse(status="success")
    if code in (PAM_NEW_AUTHTOK_REQD, PAM_AUTHTOK_EXPIRED):
        return PAMAuthResponse(status="password_change_required")
    return PAMAuthResponse(status="failure")
