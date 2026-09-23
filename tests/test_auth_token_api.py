from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError

from wlanpi_core.api.api_v1.endpoints.auth_api import generate_token, revoke_token
from wlanpi_core.schemas.auth import TokenRequest


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
        await generate_token(request, TokenRequest(device_id=device_id))

    assert exc.value.status_code == 412
    token_manager.create_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_token_normalizes_device_id():
    token_manager = SimpleNamespace(create_token=AsyncMock(return_value="jwt"))
    request = _request_with_token_manager(token_manager)

    response = await generate_token(request, TokenRequest(device_id="  mcp-client  "))

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
        await generate_token(request, TokenRequest(device_id="mcp-client"))

    assert exc.value.status_code == 500
    assert "database unavailable" not in exc.value.detail


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
