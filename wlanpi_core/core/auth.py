"""Authentication helpers for the API: HMAC, JWT, and bearer tokens."""

import hashlib
import hmac
import ipaddress
import urllib
from typing import Any

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from wlanpi_core.core.logging import get_logger
from wlanpi_core.core.token import AUTH_CLOCK_NOT_SET

log = get_logger(__name__)

SECURITY = HTTPBearer(auto_error=False)
DEFAULT_SECURITY = Security(SECURITY)
DEFAULT_DEPENDS = Depends(SECURITY)
AUTH_CLOCK_MESSAGE = "NTP needs set; cannot proceed"


class AuthClockNotSetError(Exception):
    """Raised when the auth clock is not set (NTP)."""


async def verify_auth_wrapper(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = DEFAULT_SECURITY,
) -> Any:
    """Select authentication from the credential presented."""

    # TODO(#139): HMAC is a transitional compatibility path. Move every client to
    # Bearer authentication, dispatch on presented credentials instead of source
    # address, and then remove the shared HMAC secret and this branch.

    if credentials:
        return await verify_jwt_token(request, credentials)
    authorization = request.headers.get("Authorization", "")
    authorization_parts = authorization.split(maxsplit=1)
    if authorization_parts and authorization_parts[0].lower() == "bearer":
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    if request.headers.get("X-Request-Signature"):
        return await verify_hmac(request)
    raise HTTPException(
        status_code=401,
        detail="Authentication required: Bearer token or request signature",
    )


async def verify_local_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = DEFAULT_SECURITY,
) -> Any:
    """Bearer or HMAC, localhost only.

    For the password-handling PAM endpoints: accept a device JWT (so on-device
    services do not need the shared secret) or the legacy localhost HMAC, but
    never expose them off-device.
    """
    if not is_localhost_request(request):
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: endpoint available only on localhost",
        )
    return await verify_auth_wrapper(request, credentials)


async def verify_jwt_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = DEFAULT_SECURITY,
) -> Any:
    """Verify a JWT bearer token and return the validation result."""
    if not credentials:
        log.error("Authentication failed: No bearer token provided")
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = credentials.credentials
    validation_result = await request.app.state.token_manager.verify_token(token)
    if not validation_result.is_valid:
        log.error(f"Token validation failed: {validation_result.error}")
        if validation_result.error == AUTH_CLOCK_NOT_SET:
            raise AuthClockNotSetError
        raise HTTPException(status_code=401, detail="Unauthorized")
    return validation_result


async def verify_hmac(request: Request) -> Any:
    """Verify HMAC signature for internal requests."""
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
    query_string = (
        urllib.parse.urlencode(request.query_params) if request.query_params else ""
    )
    # verify path + query
    canonical_string = (
        f"{request.method}\n{request.url.path}\n{query_string}\n{body.decode()}"
    )

    calculated = hmac.new(secret, canonical_string.encode(), hashlib.sha256).hexdigest()

    log.debug(f"Method: {request.method}")
    log.debug(f"Path: {request.url.path}")
    log.debug(f"Query string: {query_string}")

    if not hmac.compare_digest(signature, calculated):
        raise HTTPException(
            status_code=401,
            detail="Invalid signature",
            headers={"X-Requires-Signature": "true"},
        )

    return True


def is_localhost_request(request: Request) -> bool:
    """Check if request comes from loopback address (127.0.0.1/::1)."""
    try:
        log.debug(f"Client: {request.client}")
        log.debug(f"Scope client: {request.scope.get('client')}")
        log.debug(f"X-Real-IP: {request.headers.get('X-Real-IP')}")

        peer_host = request.client.host if request.client else None
        if not peer_host and request.scope.get("client"):
            client_tuple = request.scope.get("client")
            if client_tuple and len(client_tuple) > 0:
                peer_host = client_tuple[0]

        if peer_host and not ipaddress.ip_address(peer_host).is_loopback:
            return False

        client_host = request.headers.get("X-Real-IP") or peer_host
        if not client_host:
            log.warning("Could not determine client IP address")
            return False

        client_ip = ipaddress.ip_address(client_host)
        is_loopback = client_ip.is_loopback
        log.debug(f"IP: {client_ip}, is_loopback: {is_loopback}")
        return is_loopback

    except Exception:
        log.exception("Error in is_localhost_request")
        return False
