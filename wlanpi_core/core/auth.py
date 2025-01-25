import hashlib
import hmac
import ipaddress
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from wlanpi_core.core.logging import get_logger
from wlanpi_core.core.tokenmanager import TokenError

log = get_logger(__name__)

SECURITY = HTTPBearer(auto_error=False)
DEFAULT_SECURITY = Security(SECURITY)
DEFAULT_DEPENDS = Depends(SECURITY)


async def verify_auth_wrapper(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = DEFAULT_SECURITY,
):
    """
    Use HMAC for internal requests, JWT for external requests, OTG for token bootstrap
    """

    if is_otg_request(request):
        pass
    elif is_localhost_request(request):
        return await verify_hmac(request)
    else:
        if not credentials:
            raise HTTPException(status_code=401, detail="Bearer token required")
        return await verify_jwt_token(request, credentials)


async def verify_jwt_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = DEFAULT_SECURITY,
):
    if not credentials:
        log.error("Authentication failed: No bearer token provided")
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = credentials.credentials
    try:
        validation_result = await request.app.state.token_manager.verify_token(token)
        if not validation_result.is_valid:
            log.error(f"Token validation failed: {validation_result.error}")
            raise HTTPException(status_code=401, detail="Unauthorized")
        return validation_result
    except TokenError:
        log.exception("Token verification failed")
        raise HTTPException(status_code=401, detail="Unauthorized")


async def verify_hmac(request: Request):
    """Verify HMAC signature for internal requests"""
    if not is_localhost_request(request):
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: endpoint available only on localhost",
        )

    signature = request.headers.get("X-Request-Signature")
    if not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing signature header",
            headers={"X-Requires-Signature": "true"},
        )

    secret = request.app.state.security_manager.shared_secret
    body = await request.body()
    canonical_string = f"{request.method}\n{request.url.path}\n{body.decode()}"

    calculated = hmac.new(secret, canonical_string.encode(), hashlib.sha256).hexdigest()

    log.debug(f"Server calculated signature: {calculated}")
    log.debug(f"Client provided signature: {signature}")

    if not hmac.compare_digest(signature, calculated):
        raise HTTPException(
            status_code=401,
            detail="Invalid signature",
            headers={"X-Requires-Signature": "true"},
        )

    return True


def is_localhost_request(request: Request) -> bool:
    """Check if request comes from loopback address (127.0.0.1/::1)"""
    try:
        # log.debug(f"Headers: {request.headers}")
        log.debug(f"Client: {request.client}")
        log.debug(f"Scope client: {request.scope.get('client')}")
        log.debug(f"X-Forwarded-For: {request.headers.get('X-Forwarded-For')}")
        log.debug(f"X-Real-IP: {request.headers.get('X-Real-IP')}")

        if request.headers.get("X-Real-IP"):
            client_host = request.headers.get("X-Real-IP")
            log.debug(f"Using X-Real-IP: {client_host}")
        elif request.headers.get("X-Forwarded-For"):
            client_host = request.headers.get("X-Forwarded-For").split(",")[0].strip()
            log.debug(f"Using X-Forwarded-For: {client_host}")
        elif request.client and request.client.host:
            client_host = request.client.host
            log.debug(f"Using request.client.host: {client_host}")
        elif request.scope.get("client"):
            client_tuple = request.scope.get("client")
            if client_tuple and len(client_tuple) > 0:
                client_host = client_tuple[0]
                log.debug(f"Using scope client: {client_host}")
        else:
            log.warning("Could not determine client IP address")
            return False

        client_ip = ipaddress.ip_address(client_host)
        is_loopback = client_ip.is_loopback
        log.debug(f"IP: {client_ip}, is_loopback: {is_loopback}")
        return is_loopback

    except Exception:
        log.exception("Error in is_localhost_request")
        return False


def is_otg_request(request: Request) -> bool:
    """Check if request comes from OTG interface"""
    try:
        return False
    except Exception:
        log.exception("Error in is_otg_request")
        return False
