import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from fastapi.requests import Request
from fastapi.security import HTTPAuthorizationCredentials

import wlanpi_core.core.auth as auth_module
from wlanpi_core.app import auth_clock_not_set_handler
from wlanpi_core.cli import network_config
from wlanpi_core.core.auth import (
    AuthClockNotSetError,
    is_localhost_request,
    verify_auth_wrapper,
    verify_hmac,
    verify_local_auth,
)
from wlanpi_core.core.token import AUTH_CLOCK_NOT_SET, TokenValidationResult


def create_mock_request(client_host="127.0.0.1", headers=None, scope_client=None):
    """Create a consistent mock request."""
    request = Mock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/v1/test"
    request.query_params = {}
    request.headers = headers or {}
    request.client = Mock()
    request.client.host = client_host

    # Add scope attribute
    request.scope = {
        "client": scope_client
        or (client_host, 12345)  # Typical scope client tuple (host, port)
    }

    return request


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request with necessary attributes."""
    return create_mock_request()


@pytest.fixture
def mock_request_with_query():
    """Create a mock request with query parameters."""
    request = create_mock_request()
    request.method = "GET"
    request.query_params = {"param1": "value1", "param2": "value2"}
    return request


@pytest.fixture
def mock_app_state():
    """Create mock application state with security manager."""
    app_state = Mock()
    app_state.security_manager.shared_secret = b"test_secret"
    return app_state


@pytest.mark.asyncio
async def test_verify_hmac_success(mock_request, mock_app_state):
    """Test successful HMAC verification."""

    # Set up request body and calculate expected signature
    body = b'{"test": "data"}'
    canonical_string = "POST\n/api/v1/test\n\n" + body.decode()
    expected_signature = hmac.new(
        mock_app_state.security_manager.shared_secret,
        canonical_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Configure mock request
    mock_request.app.state = mock_app_state
    mock_request.body = AsyncMock(return_value=body)
    mock_request.headers["X-Request-Signature"] = expected_signature

    # Test verification
    result = await verify_hmac(mock_request)
    assert result is True


@pytest.mark.asyncio
async def test_verify_hmac_with_params(mock_request_with_query, mock_app_state):
    """Test HMAC verification with query parameters."""
    body = b""
    query_string = "param1=value1&param2=value2"
    canonical_string = f"GET\n/api/v1/test\n{query_string}\n"
    expected_signature = hmac.new(
        mock_app_state.security_manager.shared_secret,
        canonical_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    mock_request_with_query.app.state = mock_app_state
    mock_request_with_query.body = AsyncMock(return_value=body)
    mock_request_with_query.headers["X-Request-Signature"] = expected_signature

    result = await verify_hmac(mock_request_with_query)
    assert result is True


@pytest.mark.asyncio
async def test_verify_hmac_invalid_signature(mock_request, mock_app_state):
    """Test HMAC verification with invalid signature."""
    mock_request.app.state = mock_app_state
    mock_request.body = AsyncMock(return_value=b'{"test": "data"}')
    mock_request.headers["X-Request-Signature"] = "invalid_signature"

    with pytest.raises(HTTPException) as exc_info:
        await verify_hmac(mock_request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid signature"


@pytest.mark.asyncio
async def test_verify_hmac_missing_signature(mock_request, mock_app_state):
    """Test HMAC verification with missing signature header."""
    mock_request.app.state = mock_app_state
    mock_request.body = Mock(return_value=b'{"test": "data"}')

    with pytest.raises(HTTPException) as exc_info:
        await verify_hmac(mock_request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing signature header"


@pytest.mark.asyncio
async def test_verify_hmac_non_localhost(mock_request, mock_app_state):
    """Test HMAC verification from non-localhost IP."""
    mock_request.client.host = "192.168.1.100"
    mock_request.scope["client"] = ("192.168.1.100", 12345)
    mock_request.app.state = mock_app_state

    with pytest.raises(HTTPException) as exc_info:
        await verify_hmac(mock_request)
    assert exc_info.value.status_code == 403
    assert "Access forbidden" in exc_info.value.detail


def test_is_localhost_request_valid():
    """Test localhost detection with valid localhost IP."""
    request = create_mock_request(client_host="127.0.0.1")
    assert is_localhost_request(request) is True


def test_is_localhost_request_ipv6():
    """Test localhost detection with IPv6 localhost."""
    request = create_mock_request(client_host="::1")
    assert is_localhost_request(request) is True


def test_is_localhost_request_non_localhost():
    """Test localhost detection with non-localhost IP."""
    request = create_mock_request(
        client_host="192.168.1.100", scope_client=("192.168.1.100", 12345)
    )
    assert is_localhost_request(request) is False


def test_remote_peer_cannot_spoof_x_real_ip():
    request = create_mock_request(
        client_host="10.0.0.1",
        headers={"X-Real-IP": "127.0.0.1"},
        scope_client=("10.0.0.1", 12345),
    )
    assert is_localhost_request(request) is False


def test_remote_peer_cannot_spoof_x_forwarded_for():
    request = create_mock_request(
        client_host="10.0.0.1",
        headers={"X-Forwarded-For": "127.0.0.1, 10.0.0.1"},
        scope_client=("10.0.0.1", 12345),
    )
    assert is_localhost_request(request) is False


def test_unix_proxy_uses_x_real_ip():
    request = create_mock_request(headers={"X-Real-IP": "127.0.0.1"})
    request.client = None
    request.scope["client"] = None

    assert is_localhost_request(request) is True


def test_is_localhost_request_with_no_client():
    """Test localhost detection when client info is missing."""
    request = create_mock_request()
    request.client = None
    request.scope["client"] = None
    assert is_localhost_request(request) is False


def test_is_localhost_request_with_empty_headers():
    """Test localhost detection with empty headers."""
    request = create_mock_request()
    request.headers = {}
    assert is_localhost_request(request) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client_host", "bearer", "signature", "expected"),
    [
        ("127.0.0.1", True, False, "jwt"),
        ("::1", True, False, "jwt"),
        ("192.168.1.100", True, False, "jwt"),
        ("127.0.0.1", False, True, "hmac"),
        ("::1", False, True, "hmac"),
        ("127.0.0.1", True, True, "jwt"),
        ("127.0.0.1", False, False, "reject"),
        ("192.168.1.100", False, False, "reject"),
    ],
)
async def test_auth_dispatches_on_credentials(
    monkeypatch, client_host, bearer, signature, expected
):
    headers = {"X-Request-Signature": "signature"} if signature else {}
    request = create_mock_request(client_host=client_host, headers=headers)
    jwt_verifier = AsyncMock(return_value="jwt")
    hmac_verifier = AsyncMock(return_value="hmac")
    monkeypatch.setattr(auth_module, "verify_jwt_token", jwt_verifier)
    monkeypatch.setattr(auth_module, "verify_hmac", hmac_verifier)
    credentials = (
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
        if bearer
        else None
    )

    if expected == "reject":
        with pytest.raises(HTTPException) as exc:
            await verify_auth_wrapper(request, credentials)
        assert exc.value.status_code == 401
    else:
        assert await verify_auth_wrapper(request, credentials) == expected

    assert jwt_verifier.await_count == (expected == "jwt")
    assert hmac_verifier.await_count == (expected == "hmac")


@pytest.mark.asyncio
async def test_verify_local_auth_rejects_non_localhost():
    request = create_mock_request(client_host="192.0.2.1")
    with pytest.raises(HTTPException) as exc:
        await verify_local_auth(request, None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_local_auth_dispatches_on_credentials(monkeypatch):
    request = create_mock_request(headers={"X-Request-Signature": "signature"})
    webui = SimpleNamespace(device_id="wlanpi-webui")
    jwt_verifier = AsyncMock(return_value=webui)
    hmac_verifier = AsyncMock(return_value="hmac")
    monkeypatch.setattr(auth_module, "verify_jwt_token", jwt_verifier)
    monkeypatch.setattr(auth_module, "verify_hmac", hmac_verifier)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    assert await verify_local_auth(request, credentials) is webui
    assert await verify_local_auth(request, None) == "hmac"


@pytest.mark.asyncio
async def test_verify_local_auth_rejects_other_device_tokens(monkeypatch):
    request = create_mock_request()
    monkeypatch.setattr(
        auth_module,
        "verify_jwt_token",
        AsyncMock(return_value=SimpleNamespace(device_id="mcp-client")),
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    with pytest.raises(HTTPException) as exc:
        await verify_local_auth(request, credentials)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [HTTPException(status_code=401), AuthClockNotSetError()]
)
async def test_bearer_failure_never_falls_back_to_hmac(monkeypatch, error):
    request = create_mock_request(headers={"X-Request-Signature": "signature"})
    jwt_verifier = AsyncMock(side_effect=error)
    hmac_verifier = AsyncMock()
    monkeypatch.setattr(auth_module, "verify_jwt_token", jwt_verifier)
    monkeypatch.setattr(auth_module, "verify_hmac", hmac_verifier)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    with pytest.raises(type(error)):
        await verify_auth_wrapper(request, credentials)

    jwt_verifier.assert_awaited_once()
    hmac_verifier.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [b"Bearer", b"Bearer   "])
async def test_malformed_bearer_never_falls_back_to_hmac(monkeypatch, authorization):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (b"authorization", authorization),
                (b"x-request-signature", b"signature"),
            ],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("localhost", 80),
            "scheme": "http",
        }
    )
    hmac_verifier = AsyncMock()
    monkeypatch.setattr(auth_module, "verify_hmac", hmac_verifier)
    credentials = await auth_module.SECURITY(request)

    with pytest.raises(HTTPException) as exc:
        await verify_auth_wrapper(request, credentials)

    assert exc.value.status_code == 401
    hmac_verifier.assert_not_awaited()


@pytest.mark.asyncio
async def test_whitespace_authorization_does_not_break_hmac(monkeypatch):
    request = create_mock_request(
        headers={"Authorization": "   ", "X-Request-Signature": "signature"}
    )
    hmac_verifier = AsyncMock(return_value="hmac")
    monkeypatch.setattr(auth_module, "verify_hmac", hmac_verifier)

    assert await verify_auth_wrapper(request, None) == "hmac"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "exception"),
    [(AUTH_CLOCK_NOT_SET, AuthClockNotSetError), ("Token revoked", HTTPException)],
)
async def test_bearer_error_mapping(error, exception):
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                token_manager=SimpleNamespace(
                    verify_token=AsyncMock(
                        return_value=TokenValidationResult(is_valid=False, error=error)
                    )
                )
            )
        )
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    with pytest.raises(exception) as exc:
        await auth_module.verify_jwt_token(request, credentials)

    if isinstance(exc.value, HTTPException):
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_clock_error_response_contract():
    response = await auth_clock_not_set_handler(
        Mock(spec=Request), AuthClockNotSetError()
    )

    assert response.status_code == 503
    assert json.loads(response.body) == {
        "error": AUTH_CLOCK_NOT_SET,
        "message": "NTP needs set; cannot proceed",
    }


def test_nginx_uses_real_client_identity():
    config = (
        Path(__file__).parents[1] / "install/etc/wlanpi-core/nginx/wlanpi_core.conf"
    ).read_text()

    assert "X-Wlanpi-Client" not in config
    assert "$wlanpi_real_ip" not in config
    assert "192.0.2.1" not in config
    assert "proxy_set_header X-Real-IP $remote_addr;" in config


def test_network_config_cli_sends_bearer_only(monkeypatch):
    cli = network_config.NetworkConfigCLI()
    cli.token = "jwt"
    response = Mock(ok=True)
    response.json.return_value = {"ok": True}
    request = Mock(return_value=response)
    monkeypatch.setattr(network_config.requests, "get", request)

    assert cli.make_request("GET", "http://localhost/test") == {"ok": True}

    headers = request.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer jwt"
    assert "X-Request-Signature" not in headers
