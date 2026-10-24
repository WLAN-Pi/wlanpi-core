import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from wlanpi_core.api.api_v1.endpoints.auth_api import generate_token, revoke_token
from wlanpi_core.asgi import app
from wlanpi_core.core.auth import CallerKind
from wlanpi_core.core.token import TokenValidationResult
from wlanpi_core.schemas.auth import TokenRequest

HMAC = CallerKind.LOCALHOST_HMAC
TOKEN_PATH = "/api/v1/auth/token"
SECRET = b"test_secret"
RESERVED_BODY = json.dumps({"device_id": "wlanpi-webui"})


def _request_with_token_manager(token_manager):
    return MagicMock(
        app=SimpleNamespace(state=SimpleNamespace(token_manager=token_manager))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("device_id", [None, "", "   "])
async def test_generate_token_returns_412_for_missing_or_blank_device_id(device_id):
    token_manager = SimpleNamespace(create_token=AsyncMock())
    request = _request_with_token_manager(token_manager)

    with pytest.raises(HTTPException) as exc:
        await generate_token(request, TokenRequest(device_id=device_id), HMAC)

    assert exc.value.status_code == 412
    token_manager.create_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_token_normalizes_device_id():
    token_manager = SimpleNamespace(create_token=AsyncMock(return_value="jwt"))
    request = _request_with_token_manager(token_manager)

    response = await generate_token(
        request, TokenRequest(device_id="  mcp-client  "), HMAC
    )

    assert response.access_token == "jwt"
    assert response.token_type == "bearer"
    assert token_manager.create_token.await_args.kwargs["device_id"] == "mcp-client"


@pytest.mark.asyncio
async def test_generate_token_maps_unexpected_error_to_500():
    token_manager = SimpleNamespace(
        create_token=AsyncMock(side_effect=RuntimeError("database unavailable"))
    )
    request = _request_with_token_manager(token_manager)

    with pytest.raises(HTTPException) as exc:
        await generate_token(request, TokenRequest(device_id="mcp-client"), HMAC)

    assert exc.value.status_code == 500
    assert "database unavailable" not in exc.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("caller", "allowed"),
    [
        pytest.param(HMAC, True, id="localhost-hmac-allowed"),
        pytest.param(True, False, id="bare-true-forbidden"),
        pytest.param(
            SimpleNamespace(device_id="wlanpi-webui"),
            False,
            id="bearer-same-device-forbidden",
        ),
        pytest.param(
            SimpleNamespace(device_id="mcp-client"),
            False,
            id="bearer-other-device-forbidden",
        ),
    ],
)
async def test_generate_token_reserves_the_pam_client_device_id(caller, allowed):
    token_manager = SimpleNamespace(create_token=AsyncMock(return_value="jwt"))
    request = _request_with_token_manager(token_manager)

    if allowed:
        await generate_token(request, TokenRequest(device_id="wlanpi-webui"), caller)
        token_manager.create_token.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as exc:
            await generate_token(
                request, TokenRequest(device_id="wlanpi-webui"), caller
            )
        assert exc.value.status_code == 403
        token_manager.create_token.assert_not_awaited()


def _bearer(device_id: str) -> TokenValidationResult:
    return TokenValidationResult(
        is_valid=True, token="caller-jwt", payload={"did": device_id}
    )


@pytest.mark.asyncio
async def test_generate_token_rejects_bearer_mint_for_another_device():
    token_manager = SimpleNamespace(create_token=AsyncMock(return_value="jwt"))
    request = _request_with_token_manager(token_manager)

    with pytest.raises(HTTPException) as exc:
        await generate_token(
            request, TokenRequest(device_id="device-b"), _bearer("device-a")
        )

    assert exc.value.status_code == 403
    token_manager.create_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_token_lets_bearer_rotate_its_own_device():
    token_manager = SimpleNamespace(create_token=AsyncMock(return_value="new-jwt"))
    request = _request_with_token_manager(token_manager)

    response = await generate_token(
        request, TokenRequest(device_id="device-a"), _bearer("device-a")
    )

    assert response.access_token == "new-jwt"
    assert response.token_type == "bearer"
    assert token_manager.create_token.await_args.kwargs["device_id"] == "device-a"


def test_token_request_bounds_device_id():
    with pytest.raises(PydanticValidationError):
        TokenRequest(device_id="x" * 129)


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", ["bearer jwt", "BEARER   jwt"])
async def test_revoke_token_accepts_normalized_bearer_scheme(authorization):
    token_manager = SimpleNamespace(
        revoke_token=AsyncMock(return_value={"status": "success"})
    )
    request = _request_with_token_manager(token_manager)
    request.headers = {"Authorization": authorization}

    validation = SimpleNamespace(device_id="mcp-client")
    await revoke_token(request, TokenRequest(device_id="mcp-client"), validation)

    token_manager.revoke_token.assert_awaited_once_with("jwt")


@pytest.mark.asyncio
async def test_revoke_token_rejects_mismatched_device_id():
    token_manager = SimpleNamespace(revoke_token=AsyncMock())
    request = _request_with_token_manager(token_manager)
    request.headers = {"Authorization": "Bearer jwt"}

    with pytest.raises(HTTPException) as exc:
        await revoke_token(
            request,
            TokenRequest(device_id="other"),
            SimpleNamespace(device_id="mcp-client"),
        )

    assert exc.value.status_code == 403
    token_manager.revoke_token.assert_not_awaited()


@pytest.fixture
def endpoint_state(monkeypatch):
    token_manager = SimpleNamespace(
        create_token=AsyncMock(return_value="jwt"), verify_token=AsyncMock()
    )
    monkeypatch.setattr(app.state, "token_manager", token_manager, raising=False)
    monkeypatch.setattr(
        app.state,
        "security_manager",
        SimpleNamespace(shared_secret=SECRET),
        raising=False,
    )
    return token_manager


def _post_token(headers):
    client = TestClient(app, client=("127.0.0.1", 50000))
    return client.post(
        TOKEN_PATH,
        content=RESERVED_BODY,
        headers={"Content-Type": "application/json", **headers},
    )


def test_reserved_device_id_accepts_real_localhost_hmac_request(endpoint_state):
    canonical = f"POST\n{TOKEN_PATH}\n\n{RESERVED_BODY}"
    signature = hmac.new(SECRET, canonical.encode(), hashlib.sha256).hexdigest()

    resp = _post_token({"X-Request-Signature": signature})

    assert resp.status_code == 200
    assert resp.json() == {"access_token": "jwt", "token_type": "bearer"}
    endpoint_state.create_token.assert_awaited_once()
    assert endpoint_state.create_token.await_args.kwargs["device_id"] == "wlanpi-webui"


def test_reserved_device_id_rejects_valid_bearer_request(endpoint_state):
    endpoint_state.verify_token.return_value = TokenValidationResult(
        is_valid=True, token="jwt", payload={"did": "mcp-client"}
    )

    resp = _post_token({"Authorization": "Bearer jwt"})

    assert resp.status_code == 403
    endpoint_state.verify_token.assert_awaited_once_with("jwt")
    endpoint_state.create_token.assert_not_awaited()


def test_bearer_cannot_mint_token_for_another_device(endpoint_state):
    endpoint_state.verify_token.return_value = TokenValidationResult(
        is_valid=True, token="jwt", payload={"did": "device-a"}
    )
    client = TestClient(app, client=("203.0.113.10", 50000))

    resp = client.post(
        TOKEN_PATH,
        content=json.dumps({"device_id": "device-b"}),
        headers={"Content-Type": "application/json", "Authorization": "Bearer jwt"},
    )

    assert resp.status_code == 403
    endpoint_state.create_token.assert_not_awaited()
