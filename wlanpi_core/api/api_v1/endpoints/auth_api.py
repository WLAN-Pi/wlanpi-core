"""
Authentication API Endpoints

This module provides API endpoints for token management,
signing key rotation, and authentication-related debug operations.
"""

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from wlanpi_core.core.auth import verify_auth_wrapper, verify_hmac, verify_jwt_token
from wlanpi_core.core.config import settings
from wlanpi_core.schemas.auth import KeyResponse, Token, TokenRequest

router = APIRouter()
from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


@router.post("/token", dependencies=[Depends(verify_auth_wrapper)])
async def generate_token(request: Request, token_request: TokenRequest):
    """Generate a new JWT token"""
    try:
        if not token_request.device_id:
            raise HTTPException(status_code=412, detail="Device ID (did) is required")

        access_token_expires = timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS)
        token = await request.app.state.token_manager.create_token(
            device_id=token_request.device_id, expires_delta=access_token_expires
        )
        return Token(access_token=token, token_type="bearer")
    except Exception:
        log.exception("Unexpected error during token generation")
        raise HTTPException(
            status_code=500, detail="Internal server error during token generation"
        )


@router.delete("/token", dependencies=[Depends(verify_jwt_token)])
async def revoke_token(request: Request, token_request: TokenRequest):
    """
    Revoke an existing token

    Args:
        request: FastAPI request object
        token_request: Token request containing device_id

    Returns:
        dict: Status message

    Raises:
        HTTPException: If token revocation fails or device_id is missing
    """
    try:
        if not token_request.device_id:
            raise HTTPException(status_code=412, detail="Device ID (did) is required")
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization header")

        token = auth.split(" ")[1]
        result = await request.app.state.token_manager.revoke_token(token)
        return result

    except HTTPException:
        raise
    except Exception:
        log.exception("Unexpected error during token revocation")
        raise HTTPException(
            status_code=500, detail="Internal server error during token revocation"
        )


# Internal key management endpoints
@router.post(
    "/signing_key", dependencies=[Depends(verify_hmac)], include_in_schema=False
)
async def new_signing_key(request: Request):
    """Create new signing key and invalidate old one"""
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
        )


@router.get(
    "/signing_keys", dependencies=[Depends(verify_hmac)], include_in_schema=False
)
async def list_all_signing_keys(request: Request):
    """List all signing keys"""
    try:
        keys = await request.app.state.token_manager.get_active_keys()
        return keys
    except Exception:
        log.exception("Unexpected error getting keys")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/debug/cache/verify", dependencies=[Depends(verify_hmac)], include_in_schema=False
)
async def verify_cache(request: Request, token: Optional[str] = None):
    """Verify cache state"""
    return await request.app.state.token_manager.verify_cache_state(token)


@router.get(
    "/debug/db-state", dependencies=[Depends(verify_hmac)], include_in_schema=False
)
async def check_db_state(request: Request):
    """Check current database state"""
    return await request.app.state.token_manager.verify_db_state()
