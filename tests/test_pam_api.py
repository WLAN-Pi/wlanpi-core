"""Tests for the internal PAM authentication endpoints."""

import sys
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from wlanpi_core.api.api_v1.endpoints.auth_api import (
    _is_administrator,
    _pam_change_password,
    pam_authenticate,
    pam_change_password,
)
from wlanpi_core.schemas.auth import (
    PAMAuthRequest,
    PAMAuthResponse,
    PAMChangePasswordRequest,
)


@pytest.fixture(autouse=True)
def no_fail_delay(monkeypatch):
    """Keep the non-administrator timing pad out of the test run time."""
    monkeypatch.setattr("wlanpi_core.api.api_v1.endpoints.auth_api._PAM_FAIL_DELAY", 0)


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
async def test_verify_expired_non_administrator_is_failure():
    """An expired password must not reveal that a non-admin's guess was right."""
    resp = await _verify("alice", "secret", NEW_AUTHTOK_REQD, admin=False)
    assert resp.status == "failure"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [SUCCESS, NEW_AUTHTOK_REQD])
async def test_non_administrator_refusal_waits_like_a_wrong_password(monkeypatch, code):
    """A fast refusal would confirm a non-admin's password was right."""
    monkeypatch.setattr(
        "wlanpi_core.api.api_v1.endpoints.auth_api._PAM_FAIL_DELAY", 0.05
    )
    started = time.monotonic()
    resp = await _verify("alice", "secret", code, admin=False)
    assert resp.status == "failure"
    assert time.monotonic() - started >= 0.05


def test_is_administrator_fails_closed_on_embedded_nul():
    assert _is_administrator("wlanpi\x00x") is False


@pytest.mark.parametrize("username", ["wlanpi\x00x", "wlanpi\n", "a\x7fb"])
def test_schema_rejects_control_characters_in_username(username):
    with pytest.raises(ValidationError):
        PAMAuthRequest(username=username, password="secret")
    with pytest.raises(ValidationError):
        PAMChangePasswordRequest(
            username=username, current_password="a", new_password="b"
        )


@pytest.mark.asyncio
async def test_change_password_same_as_current_is_rejected_before_pam():
    with patch(
        "wlanpi_core.api.api_v1.endpoints.auth_api._pam_authenticate"
    ) as authenticate:
        resp = await pam_change_password(
            PAMChangePasswordRequest(
                username="wlanpi", current_password="same", new_password="same"
            )
        )
    assert resp.status == "password_rejected"
    authenticate.assert_not_called()


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
async def test_change_password_non_expired_refusal_waits_like_a_wrong_password(
    monkeypatch,
):
    """A fast "failure" would confirm the current password was right."""
    monkeypatch.setattr(
        "wlanpi_core.api.api_v1.endpoints.auth_api._PAM_FAIL_DELAY", 0.05
    )
    started = time.monotonic()
    resp = await _change("alice", "current", "new", SUCCESS, SUCCESS, admin=False)
    assert resp.status == "failure"
    assert time.monotonic() - started >= 0.05


@pytest.mark.asyncio
async def test_change_password_wrong_current_is_failure():
    resp = await _change("wlanpi", "wrong", "new", AUTH_ERR, SUCCESS)
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_change_password_non_administrator_is_failure():
    resp = await _change("alice", "old", "new", NEW_AUTHTOK_REQD, SUCCESS, admin=False)
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_change_password_weak_new_password_is_rejected():
    resp = await _change("wlanpi", "old", "weak", NEW_AUTHTOK_REQD, AUTHTOK_ERR)
    assert resp.status == "password_rejected"


def test_change_password_runs_pam_as_an_expired_token_change():
    """Root with no flags makes pam_unix skip the password policy (audit #1)."""
    pamela = MagicMock()
    pamela.PAMError = type("PAMError", (Exception,), {})
    pamela.PAM_CHAUTHTOK.return_value = 0
    with patch.dict(sys.modules, {"pamela": pamela}):
        assert _pam_change_password("wlanpi", "old", "new") == 0

    pamela.new_simple_password_conv.assert_called_once_with(
        ("old", "new", "new"), "utf-8"
    )
    handle = pamela.pam_start.return_value
    pamela.PAM_CHAUTHTOK.assert_called_once_with(handle, 0x0020)
    pamela.change_password.assert_not_called()


def test_change_password_returns_pam_error_code():
    pamela = MagicMock()
    pamela.PAMError = type("PAMError", (Exception,), {"errno": AUTHTOK_ERR})
    pamela.pam_end.side_effect = pamela.PAMError()
    with patch.dict(sys.modules, {"pamela": pamela}):
        assert _pam_change_password("wlanpi", "old", "weak") == AUTHTOK_ERR


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
