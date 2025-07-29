import hashlib
import hmac
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from fastapi.requests import Request

from wlanpi_core.core.auth import is_localhost_request, verify_hmac


def create_mock_request(client_host="127.0.0.1", headers=None, scope_client=None):
    """Helper function to create a consistent mock request"""
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
    """Create a mock FastAPI request with necessary attributes"""
    return create_mock_request()


@pytest.fixture
def mock_request_with_query():
    """Create a mock request with query parameters"""
    request = create_mock_request()
    request.method = "GET"
    request.query_params = {"param1": "value1", "param2": "value2"}
    return request


@pytest.fixture
def mock_app_state():
    """Create mock application state with security manager"""
    app_state = Mock()
    app_state.security_manager.shared_secret = b"test_secret"
    return app_state


@pytest.mark.asyncio
async def test_verify_hmac_success(mock_request, mock_app_state):
    """Test successful HMAC verification"""

    # Set up request body and calculate expected signature
    body = b'{"test": "data"}'
    canonical_string = f"POST\n/api/v1/test\n\n" + body.decode()
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
    """Test HMAC verification with query parameters"""
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
    """Test HMAC verification with invalid signature"""
    mock_request.app.state = mock_app_state
    mock_request.body = AsyncMock(return_value=b'{"test": "data"}')
    mock_request.headers["X-Request-Signature"] = "invalid_signature"

    with pytest.raises(HTTPException) as exc_info:
        await verify_hmac(mock_request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid signature"


@pytest.mark.asyncio
async def test_verify_hmac_missing_signature(mock_request, mock_app_state):
    """Test HMAC verification with missing signature header"""
    mock_request.app.state = mock_app_state
    mock_request.body = Mock(return_value=b'{"test": "data"}')

    with pytest.raises(HTTPException) as exc_info:
        await verify_hmac(mock_request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing signature header"


@pytest.mark.asyncio
async def test_verify_hmac_non_localhost(mock_request, mock_app_state):
    """Test HMAC verification from non-localhost IP"""
    mock_request.client.host = "192.168.1.100"
    mock_request.scope["client"] = ("192.168.1.100", 12345)
    mock_request.app.state = mock_app_state

    with pytest.raises(HTTPException) as exc_info:
        await verify_hmac(mock_request)
    assert exc_info.value.status_code == 403
    assert "Access forbidden" in exc_info.value.detail


def test_is_localhost_request_valid():
    """Test localhost detection with valid localhost IP"""
    request = create_mock_request(client_host="127.0.0.1")
    assert is_localhost_request(request) is True


def test_is_localhost_request_ipv6():
    """Test localhost detection with IPv6 localhost"""
    request = create_mock_request(client_host="::1")
    assert is_localhost_request(request) is True


def test_is_localhost_request_non_localhost():
    """Test localhost detection with non-localhost IP"""
    request = create_mock_request(
        client_host="192.168.1.100", scope_client=("192.168.1.100", 12345)
    )
    assert is_localhost_request(request) is False


def test_is_localhost_request_with_x_real_ip():
    """Test localhost detection with X-Real-IP header"""
    request = create_mock_request(
        client_host="10.0.0.1",
        headers={"X-Real-IP": "127.0.0.1"},
        scope_client=("10.0.0.1", 12345),
    )
    assert is_localhost_request(request) is True


def test_is_localhost_request_with_x_forwarded_for():
    """Test localhost detection with X-Forwarded-For header"""
    request = create_mock_request(
        client_host="10.0.0.1",
        headers={"X-Forwarded-For": "127.0.0.1, 10.0.0.1"},
        scope_client=("10.0.0.1", 12345),
    )
    assert is_localhost_request(request) is True


def test_is_localhost_request_with_no_client():
    """Test localhost detection when client info is missing"""
    request = create_mock_request()
    request.client = None
    request.scope["client"] = None
    assert is_localhost_request(request) is False


def test_is_localhost_request_with_empty_headers():
    """Test localhost detection with empty headers"""
    request = create_mock_request()
    request.headers = {}
    assert is_localhost_request(request) is True
