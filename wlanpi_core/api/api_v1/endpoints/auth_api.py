import base64
import logging
from datetime import timedelta
from typing import Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, Request, HTTPException
from wlanpi_core.core.auth import (
    ACCESS_TOKEN_EXPIRE_DAYS,
    KeyCache,
    TokenError,
    verify_jwt_token,
    verify_hmac,
)
from wlanpi_core.schemas.auth import TokenRequest, Token
from wlanpi_core.services import system_service

router = APIRouter()
log = logging.getLogger("uvicorn")


class KeyResponse(BaseModel):
    key_id: int
    message: str
    key: Optional[str] = None  # Base64 encoded key, only included when needed

class KeyListResponse(BaseModel):
    keys: list[dict]  


@router.post("/token", dependencies=[Depends(verify_hmac)])
async def generate_token(request: Request, token_request: TokenRequest):
    """Generate a new JWT token (internal endpoint)"""
    try:
        if not token_request.device_id:
            raise HTTPException(
                status_code=412, 
                detail="Device ID (did) is required"
            )
            
        access_token_expires = timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
        token = await request.app.state.token_manager.create_token(
            device_id=token_request.device_id, expires_delta=access_token_expires
        )
        return Token(access_token=token, token_type="bearer")
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Failed to get token: {e}")
        raise HTTPException(status_code=500, detail="Failed to get token")
    

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
            raise HTTPException(
                status_code=412, 
                detail="Device ID (did) is required"
            )
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Invalid authorization header"
            )
            
        token = auth.split(" ")[1]
        result = await request.app.state.token_manager.revoke_token(token)
        return result 
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to revoke token: {e}")
        raise HTTPException(status_code=500, detail="Failed to revoke token")
    
# Internal key management endpoints
@router.post("/signing_key", dependencies=[Depends(verify_hmac)])
async def new_signing_key(request: Request):
    """Create new signing key and invalidate old one"""
    try:
        key_cache = KeyCache()
        key_cache.clear()

        key_id, key = await request.app.state.token_manager.rotate_key()
        
        key_b64 = base64.b64encode(key).decode('ascii') if key else None
        return KeyResponse(
            key_id=key_id,
            message="New signing key created",
            key=key_b64 
        )
    except Exception as e:
        log.error(f"Failed to create signing key: {e}")
        raise HTTPException(status_code=500, detail="Failed to create signing key")

@router.get("/signing_keys", dependencies=[Depends(verify_hmac)])
async def list_all_signing_keys(request: Request):
    """List all signing keys"""
    try:
        return await request.app.state.token_manager.get_active_keys()
    except Exception as e:
        log.error(f"Failed to get all signing keys: {e}")
        raise HTTPException(status_code=500, detail="Failed to get all signing keys")

@router.get("/debug/cache/verify", dependencies=[Depends(verify_hmac)])
async def verify_cache(request: Request, token: Optional[str] = None):
    """Verify cache state"""
    return await request.app.state.token_manager.verify_cache_state(token)

@router.get("/debug/db-state", dependencies=[Depends(verify_hmac)])
async def check_db_state(request: Request):
    """Check current database state"""
    return await request.app.state.token_manager.verify_db_state()