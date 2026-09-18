"""Tests for the internal PAM authentication endpoints."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from wlanpi_core.api.api_v1.endpoints.auth_api import (
    pam_authenticate,
    pam_change_password,
)
from wlanpi_core.schemas.auth import (
    PAMAuthRequest,
    PAMAuthResponse,
    PAMChangePasswordRequest,
)

SUCCESS = 0
AUTH_ERR = 7
NEW_AUTHTOK_REQD = 12
AUTHTOK_ERR = 20
MODULE_UNKNOWN = 28


async def _verify(username, password, code, admin=True):
    with (
        patch(
            "wlanpi_core.api.api_v1.endpoints.auth_api._pam_authenticate",
            return_value=code,
        ),
        patch(
            "wlanpi_core.api.api_v1.endpoints.auth_api._is_administrator",
            return_value=admin,
        ),
    ):
        return await pam_authenticate(
            PAMAuthRequest(username=username, password=password)
        )


async def _change(username, current, new, old_code, change_code, admin=True):
    with (
        patch(
            "wlanpi_core.api.api_v1.endpoints.auth_api._pam_authenticate",
            side_effect=[old_code, SUCCESS],
        ),
        patch(
            "wlanpi_core.api.api_v1.endpoints.auth_api._pam_change_password",
            return_value=change_code,
        ),
        patch(
            "wlanpi_core.api.api_v1.endpoints.auth_api._is_administrator",
            return_value=admin,
        ),
    ):
        return await pam_change_password(
            PAMChangePasswordRequest(
                username=username,
                current_password=current,
                new_password=new,
            )
        )


@pytest.mark.asyncio
async def test_verify_success_for_administrator():
    resp = await _verify("wlanpi", "secret", SUCCESS)
    assert resp.status == "success"


@pytest.mark.asyncio
async def test_verify_non_administrator_is_failure():
    resp = await _verify("alice", "secret", SUCCESS, admin=False)
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_verify_wrong_password_is_failure():
    resp = await _verify("wlanpi", "wrong", AUTH_ERR)
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_verify_expired_password_is_password_change_required():
    resp = await _verify("wlanpi", "secret", NEW_AUTHTOK_REQD)
    assert resp.status == "password_change_required"


@pytest.mark.asyncio
async def test_verify_pam_config_error_is_503():
    with pytest.raises(HTTPException) as exc:
        await _verify("wlanpi", "secret", MODULE_UNKNOWN)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_change_password_success():
    resp = await _change("wlanpi", "old", "new", NEW_AUTHTOK_REQD, SUCCESS)
    assert resp.status == "success"


@pytest.mark.asyncio
async def test_change_password_with_non_expired_current_is_failure():
    resp = await _change("wlanpi", "current", "new", SUCCESS, SUCCESS)
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_change_password_wrong_current_is_failure():
    resp = await _change("wlanpi", "wrong", "new", AUTH_ERR, SUCCESS)
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_change_password_non_administrator_is_failure():
    resp = await _change("alice", "old", "new", NEW_AUTHTOK_REQD, SUCCESS, admin=False)
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_change_password_weak_new_password_is_failure():
    resp = await _change("wlanpi", "old", "weak", NEW_AUTHTOK_REQD, AUTHTOK_ERR)
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_change_password_pam_config_error_is_503():
    with pytest.raises(HTTPException) as exc:
        await _change("wlanpi", "old", "new", NEW_AUTHTOK_REQD, MODULE_UNKNOWN)
    assert exc.value.status_code == 503


def test_schema_rejects_empty_password():
    with pytest.raises(ValidationError):
        PAMAuthRequest(username="wlanpi", password="")


def test_schema_rejects_missing_username():
    with pytest.raises(ValidationError):
        PAMAuthRequest(username="", password="secret")


def test_passwords_are_secret():
    req = PAMAuthRequest(username="wlanpi", password="hunter2")
    assert "hunter2" not in repr(req)
    assert str(req.password) == "**********"


def test_response_model_status_examples():
    assert PAMAuthResponse(status="success").status == "success"
