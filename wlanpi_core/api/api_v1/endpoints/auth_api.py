"""
Authentication API Endpoints.

This module provides API endpoints for token management,
signing key rotation, and authentication-related debug operations.
"""

import asyncio
import grp
import os
import pwd
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from wlanpi_core.api.openapi_docs import RESPONSES_AUTH
from wlanpi_core.core.auth import (
    PAM_CLIENT_DEVICE_ID,
    verify_auth_wrapper,
    verify_hmac,
    verify_jwt_token,
    verify_local_auth,
)
from wlanpi_core.core.config import settings
from wlanpi_core.core.logging import get_logger
from wlanpi_core.schemas.auth import (
    KeyResponse,
    PAMAuthRequest,
    PAMAuthResponse,
    PAMChangePasswordRequest,
    Token,
    TokenRequest,
    TokenRevokeResponse,
)

router = APIRouter()

log = get_logger(__name__)

PAM_SERVICE = "wlanpi-webui"

# linux-pam return codes (pamela does not export them): ordinary auth/account
# denials map to "failure"; anything else is a service/configuration error.
_PAM_AUTH_DENIED = frozenset(
    {
        6,  # PAM_PERM_DENIED
        7,  # PAM_AUTH_ERR
        9,  # PAM_AUTHINFO_UNAVAIL
        10,  # PAM_USER_UNKNOWN
        11,  # PAM_MAXTRIES
        13,  # PAM_ACCT_EXPIRED
        20,  # PAM_AUTHTOK_ERR (weak new password)
        21,  # PAM_AUTHTOK_RECOVERY_ERR
        22,  # PAM_AUTHTOK_LOCK_BUSY
        23,  # PAM_AUTHTOK_DISABLE_AGING
        24,  # PAM_TRY_AGAIN
    }
)
_PAM_EXPIRED = frozenset({12, 27})  # PAM_NEW_AUTHTOK_REQD / PAM_AUTHTOK_EXPIRED
_PAM_AUTHTOK_ERR = 20  # the new password failed the PAM password policy
# pam_unix's delay after a wrong password (about 2 s). A non-administrator's
# correct password is refused after the same wait, so the response time does
# not confirm the guess. ponytail: fixed value; measure if pam_unix changes.
_PAM_FAIL_DELAY = 2.0
# linux-pam flag (not exported by pamela): change only an expired token. It
# also makes pam_unix apply its policy (minlen, obscure) and verify the current
# password, which it skips for root without it.
_PAM_CHANGE_EXPIRED_AUTHTOK = 0x0020


def _require_device_id(token_request: TokenRequest) -> str:
    device_id = (token_request.device_id or "").strip()
    if not device_id:
        raise HTTPException(status_code=412, detail="Device ID (did) is required")
    return device_id


def _pam_authenticate(username: str, password: str) -> int:
    """Run pamela.authenticate, returning the PAM return code (0 = success)."""
    import pamela  # lazy: keeps core importable without pamela installed

    try:
        pamela.authenticate(username, password, service=PAM_SERVICE)
        return 0
    except pamela.PAMError as exc:
        return exc.errno


def _pam_change_password(
    username: str, current_password: str, new_password: str
) -> int:
    """Change an expired password through PAM, returning the PAM return code.

    Not pamela.change_password: that calls pam_chauthtok with no flags, and
    pam_unix then treats root as an administrator setting any password, which
    skips the password policy entirely. The conversation answers the current
    password prompt, then the new password twice.
    """
    import pamela  # lazy

    conv = pamela.new_simple_password_conv(
        (current_password, new_password, new_password), "utf-8"
    )
    try:
        handle = pamela.pam_start(PAM_SERVICE, username, conv_func=conv)
        pamela.pam_end(
            handle, pamela.PAM_CHAUTHTOK(handle, _PAM_CHANGE_EXPIRED_AUTHTOK)
        )
        return 0
    except pamela.PAMError as exc:
        return exc.errno


def _is_administrator(username: str) -> bool:
    """Return whether username is in the sudo group; fails closed on errors."""
    try:
        gid = pwd.getpwnam(username).pw_gid
        sudo_gid = grp.getgrnam("sudo").gr_gid
    except (KeyError, ValueError):  # ValueError: embedded NUL
        return False
    return sudo_gid in os.getgrouplist(username, gid)


async def _refuse_non_administrator() -> PAMAuthResponse:
    """Answer like a wrong password, including pam_unix's failure delay."""
    await asyncio.sleep(_PAM_FAIL_DELAY)
    return PAMAuthResponse(status="failure")


def _status_from_code(code: int) -> str:
    """Map a PAM return code to an API status; infra errors become 503."""
    if code == 0:
        return "success"
    if code in _PAM_EXPIRED:
        return "password_change_required"
    if code in _PAM_AUTH_DENIED:
        return "failure"
    log.warning("PAM returned unexpected code %s", code)
    raise HTTPException(status_code=503, detail="Authentication service unavailable")


@router.post(
    "/pam",
    response_model=PAMAuthResponse,
    include_in_schema=False,
    dependencies=[Depends(verify_local_auth)],
)
async def pam_authenticate(body: PAMAuthRequest) -> PAMAuthResponse:
    """Verify a local account password against PAM (localhost only).

    Accepts the `wlanpi-webui` bearer token or the legacy localhost HMAC.
    """
    password = body.password.get_secret_value()

    code = await asyncio.to_thread(_pam_authenticate, body.username, password)
    status = _status_from_code(code)
    # Non-administrators get the same answer as a wrong password, including
    # when their password has expired, so the status reveals nothing more.
    if status != "failure" and not await asyncio.to_thread(
        _is_administrator, body.username
    ):
        return await _refuse_non_administrator()
    return PAMAuthResponse(status=status)


@router.post(
    "/pam/change",
    response_model=PAMAuthResponse,
    include_in_schema=False,
    dependencies=[Depends(verify_local_auth)],
)
async def pam_change_password(body: PAMChangePasswordRequest) -> PAMAuthResponse:
    """Change an expired password through PAM (localhost only).

    Accepts the `wlanpi-webui` bearer token or the legacy localhost HMAC.

    Only expired passwords can be changed here (first boot). The current
    password is verified first and is never stored or returned. A new password
    that fails the system password policy returns ``password_rejected``.
    """
    username = body.username
    current = body.current_password.get_secret_value()
    new = body.new_password.get_secret_value()
    if new == current:
        return PAMAuthResponse(status="password_rejected")

    old_code = await asyncio.to_thread(_pam_authenticate, username, current)
    if old_code not in _PAM_EXPIRED:
        # Wrong current password, or the account is not expired
        if old_code in _PAM_AUTH_DENIED or old_code == 0:
            return PAMAuthResponse(status="failure")
        raise HTTPException(
            status_code=503, detail="Authentication service unavailable"
        )
    if not await asyncio.to_thread(_is_administrator, username):
        return await _refuse_non_administrator()

    code = await asyncio.to_thread(_pam_change_password, username, current, new)
    if code == _PAM_AUTHTOK_ERR:
        # The current password was verified above, so this is the new one.
        return PAMAuthResponse(status="password_rejected")
    if code != 0:
        return PAMAuthResponse(status=_status_from_code(code))

    verified = await asyncio.to_thread(_pam_authenticate, username, new)
    if verified != 0:
        log.warning("Password changed but re-verification failed (code %s)", verified)
        raise HTTPException(
            status_code=503, detail="Authentication service unavailable"
        )
    return PAMAuthResponse(status="success")


@router.post(
    "/token",
    response_model=Token,
    summary="Issue JWT bearer token",
    responses={
        401: RESPONSES_AUTH[401],
        403: {"description": "device_id is reserved for on-device use"},
        412: {"description": "device_id missing from request body"},
        500: {"description": "Token generation failed"},
    },
)
async def generate_token(
    request: Request,
    token_request: TokenRequest,
    caller: Annotated[Any, Depends(verify_auth_wrapper)],
) -> Any:
    """
    Issue a JWT for remote clients.

    **Authentication for this call:** localhost HMAC (`X-Request-Signature`) from
    on-device services. Remote HTTP clients already holding a Bearer token may also
    call this to rotate. Pure remote bootstrap requires a device-local pairing step
    (UI proxy) — see `docs/API-INTEGRATION-GUIDE.md` §1.

    The `wlanpi-webui` device id is reserved: only localhost HMAC callers can
    mint it (403 otherwise).

    Send the returned `access_token` as `Authorization: Bearer <token>` on all
    subsequent API calls until expiry (default 7 days) or `DELETE /auth/token`.
    """
    try:
        device_id = _require_device_id(token_request)
        # Only HMAC callers (root, via getjwt) get True and may mint the PAM
        # client's id; no bearer may, not even one already issued for it.
        if device_id == PAM_CLIENT_DEVICE_ID and caller is not True:
            raise HTTPException(
                status_code=403, detail="device_id is reserved for on-device use"
            )

        access_token_expires = timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS)
        token = await request.app.state.token_manager.create_token(
            device_id=device_id, expires_delta=access_token_expires
        )
        return Token(access_token=token, token_type="bearer")
    except HTTPException:
        raise
    except Exception:
        log.exception("Unexpected error during token generation")
        raise HTTPException(
            status_code=500, detail="Internal server error during token generation"
        ) from None


@router.delete(
    "/token",
    response_model=TokenRevokeResponse,
    summary="Revoke current JWT",
    responses={
        401: RESPONSES_AUTH[401],
        403: {"description": "device_id does not match the token being revoked"},
        412: {"description": "device_id missing from request body"},
        500: {"description": "Revocation failed"},
    },
)
async def revoke_token(
    request: Request,
    token_request: TokenRequest,
    validation: Annotated[Any, Depends(verify_jwt_token)],
) -> Any:
    """
    Revoke the bearer token sent in the `Authorization` header.

    The request body must include the same `device_id` used when the token was
    issued; a mismatch is rejected with 403 and the token stays valid.
    """
    try:
        device_id = _require_device_id(token_request)
        if device_id != validation.device_id:
            raise HTTPException(
                status_code=403, detail="device_id does not match token"
            )
        auth = request.headers.get("Authorization")
        parts = auth.split() if auth else []
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization header")

        token = parts[1]
        result = await request.app.state.token_manager.revoke_token(token)
        return result

    except HTTPException:
        raise
    except Exception:
        log.exception("Unexpected error during token revocation")
        raise HTTPException(
            status_code=500, detail="Internal server error during token revocation"
        ) from None


# Internal key management endpoints
@router.post(
    "/signing_key", dependencies=[Depends(verify_hmac)], include_in_schema=False
)
async def new_signing_key(request: Request) -> Any:
    """Create new signing key and invalidate old one."""
    try:
        key_id, key_str = await request.app.state.token_manager.rotate_key()

        return KeyResponse(
            key_id=key_id, message="New signing key created", key=key_str
        )
    except Exception:
        log.exception("Unexpected error during signing key generation")

        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from None


@router.get(
    "/signing_keys", dependencies=[Depends(verify_hmac)], include_in_schema=False
)
async def list_all_signing_keys(request: Request) -> Any:
    """List all signing keys."""
    try:
        keys = await request.app.state.token_manager.get_active_keys()
        return keys
    except Exception:
        log.exception("Unexpected error getting keys")
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get(
    "/debug/db-state", dependencies=[Depends(verify_hmac)], include_in_schema=False
)
async def check_db_state(request: Request) -> Any:
    """Check current database state."""
    return await request.app.state.token_manager.verify_db_state()
