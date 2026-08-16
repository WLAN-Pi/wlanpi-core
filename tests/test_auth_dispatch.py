"""#139: auth scheme is selected from the credential presented, never from
the request's source address. Bearer wins when both credentials are present;
HMAC applies only when signature material is present; no request is ever
authenticated implicitly (the OTG fall-through is gone).

Also carries the two guard rails from the auth plan:
- the nginx config must contain no auth-related header rewriting (#139
  acceptance criterion, executable), and
- every /api route must declare an auth dependency or be explicitly
  allowlisted as public.
"""

import hashlib
import hmac as hmac_lib
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from fastapi.requests import Request
from fastapi.security import HTTPAuthorizationCredentials

from wlanpi_core.core.auth import verify_auth_wrapper, verify_hmac, verify_jwt_token

SECRET = b"test_secret"


def sign(method: str, path: str, query: str, body: bytes) -> str:
    canonical = f"{method}\n{path}\n{query}\n{body.decode()}"
    return hmac_lib.new(SECRET, canonical.encode(), hashlib.sha256).hexdigest()


def make_request(client_host="127.0.0.1", headers=None, body=b"", token_valid=True):
    request = Mock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/v1/test"
    request.query_params = {}
    request.headers = headers or {}
    request.client = Mock()
    request.client.host = client_host
    request.scope = {"client": (client_host, 12345)}
    request.body = AsyncMock(return_value=body)
    validation = Mock(is_valid=token_valid, error=None if token_valid else "invalid")
    request.app.state.token_manager.verify_token = AsyncMock(return_value=validation)
    request.app.state.security_manager.shared_secret = SECRET
    return request


def bearer(token="header.payload.signature"):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# --- Dispatch matrix -------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_from_loopback_validates_as_jwt():
    """A valid Bearer must never be rejected for arriving from localhost."""
    request = make_request(client_host="127.0.0.1")

    result = await verify_auth_wrapper(request, bearer())

    assert result.is_valid
    request.app.state.token_manager.verify_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_bearer_from_off_box_validates_as_jwt():
    request = make_request(client_host="192.168.1.50")

    result = await verify_auth_wrapper(request, bearer())

    assert result.is_valid
    request.app.state.token_manager.verify_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_hmac_from_loopback_validates():
    body = b'{"test": "data"}'
    request = make_request(
        body=body,
        headers={"X-Request-Signature": sign("POST", "/api/v1/test", "", body)},
    )

    assert await verify_auth_wrapper(request, None) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("client_host", ["127.0.0.1", "192.168.1.50"])
async def test_no_credentials_is_401_regardless_of_source(client_host):
    request = make_request(client_host=client_host)

    with pytest.raises(HTTPException) as exc:
        await verify_auth_wrapper(request, None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_garbage_bearer_is_401():
    request = make_request(token_valid=False)

    with pytest.raises(HTTPException) as exc:
        await verify_auth_wrapper(request, bearer("garbage"))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_bearer_wins_when_both_credentials_present():
    body = b'{"test": "data"}'
    request = make_request(
        body=body,
        headers={"X-Request-Signature": sign("POST", "/api/v1/test", "", body)},
    )

    result = await verify_auth_wrapper(request, bearer())

    assert result.is_valid
    request.app.state.token_manager.verify_token.assert_awaited_once()
    request.body.assert_not_awaited()  # HMAC path never evaluated


@pytest.mark.asyncio
async def test_hmac_remains_localhost_only():
    """Signature material from off-box selects the HMAC scheme but the
    shared secret is on-box trust: verify_hmac rejects with 403."""
    body = b'{"test": "data"}'
    request = make_request(
        client_host="192.168.1.50",
        body=body,
        headers={"X-Request-Signature": sign("POST", "/api/v1/test", "", body)},
    )

    with pytest.raises(HTTPException) as exc:
        await verify_auth_wrapper(request, None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_client_tag_header_has_no_effect_on_dispatch():
    """The #135 sentinel is gone: X-Wlanpi-Client changes nothing."""
    body = b'{"test": "data"}'
    request = make_request(
        body=body,
        headers={
            "X-Wlanpi-Client": "mcp",
            "X-Request-Signature": sign("POST", "/api/v1/test", "", body),
        },
    )
    assert await verify_auth_wrapper(request, None) is True

    tagged_no_creds = make_request(
        client_host="192.168.1.50", headers={"X-Wlanpi-Client": "mcp"}
    )
    with pytest.raises(HTTPException) as exc:
        await verify_auth_wrapper(tagged_no_creds, None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("client_host", ["127.0.0.1", "192.168.1.50"])
@pytest.mark.parametrize(
    "headers", [None, {"X-Wlanpi-Client": "mcp"}, {"X-Forwarded-For": "10.0.0.9"}]
)
async def test_no_input_combination_authenticates_without_credentials(
    client_host, headers
):
    """Property: with no valid credential there is no authenticated outcome
    (the old OTG stub fall-through returned None, i.e. silently passed)."""
    request = make_request(client_host=client_host, headers=headers)

    with pytest.raises(HTTPException):
        await verify_auth_wrapper(request, None)


# --- nginx acceptance criterion (#139), executable -------------------------

NGINX_CONF = (
    Path(__file__).parent.parent / "install/etc/wlanpi-core/nginx/wlanpi_core.conf"
)


def test_nginx_config_contains_no_auth_header_rewriting():
    conf = NGINX_CONF.read_text()

    assert "wlanpi_client" not in conf.lower(), "#135 sentinel map must stay gone"
    assert "192.0.2.1" not in conf
    assert "proxy_set_header X-Real-IP $remote_addr;" in conf
    # No map derived from any client-supplied header.
    assert not re.search(r"map\s+\$http_", conf)


# --- Route guard rail: every /api route declares auth or is public ----------

# Routes deliberately reachable without core auth. Additions require review.
PUBLIC_API_ROUTES = {
    # Capture WS pre-dates auth; tracked debt: WLAN-Pi/wlanpi-core#141
    ("WS", "/api/v1/streaming/capture"),
    # HTML landing page listing endpoint names/descriptions — discovery
    # metadata also available via the OpenAPI docs; serves no device data.
    ("HTTP", "/api/v1"),
}

AUTH_DEPENDENCIES = {verify_auth_wrapper, verify_hmac, verify_jwt_token}


def _dependency_calls(dependant):
    calls = set()
    stack = [dependant]
    while stack:
        node = stack.pop()
        if node.call is not None:
            calls.add(node.call)
        stack.extend(node.dependencies)
    return calls


def test_every_api_route_declares_auth_or_is_allowlisted():
    from fastapi.routing import APIRoute, APIWebSocketRoute

    # Build the app directly (same pattern as test_openapi_schema) rather
    # than importing the wlanpi_core.asgi singleton: the walker must see the
    # full route table regardless of import order or module caching.
    from wlanpi_core.app import create_app

    app = create_app(debug=False)

    unprotected = []
    seen_public = set()
    for route in app.routes:
        if not getattr(route, "path", "").startswith("/api/"):
            continue
        if isinstance(route, APIRoute):
            key = ("HTTP", route.path)
        elif isinstance(route, APIWebSocketRoute):
            key = ("WS", route.path)
        else:
            continue

        if _dependency_calls(route.dependant) & AUTH_DEPENDENCIES:
            continue
        if key in PUBLIC_API_ROUTES:
            seen_public.add(key)
            continue
        unprotected.append(key)

    assert not unprotected, (
        f"Routes lack an auth dependency and are not allowlisted: {unprotected}. "
        "Add Depends(verify_auth_wrapper) or, if deliberately public, add the "
        "route to PUBLIC_API_ROUTES with a comment saying why."
    )
    stale = PUBLIC_API_ROUTES - seen_public
    assert not stale, f"PUBLIC_API_ROUTES entries no longer match any route: {stale}"
