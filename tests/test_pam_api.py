"""Tests for the internal PAM authentication endpoint."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from wlanpi_core.api.api_v1.endpoints.pam_api import (
    PAM_AUTHTOK_EXPIRED,
    PAM_NEW_AUTHTOK_REQD,
    PAM_SUCCESS,
    pam_authenticate,
)
from wlanpi_core.schemas.auth.pam import PAMAuthRequest


def _request():
    return SimpleNamespace()


async def _call(username, password, code):
    with patch("wlanpi_core.api.api_v1.endpoints.pam_api._pam_authenticate") as mock:
        mock.return_value = code
        return await pam_authenticate(
            _request(), PAMAuthRequest(username=username, password=password)
        )


@pytest.mark.asyncio
async def test_success():
    resp = await _call("wlanpi", "secret", PAM_SUCCESS)
    assert resp.status == "success"


@pytest.mark.asyncio
async def test_wrong_password_is_failure():
    resp = await _call("wlanpi", "wrong", 7)  # PAM_AUTH_ERR
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_non_sudo_account_is_failure():
    # pam_succeed_if fails the account stack for non-sudo users
    resp = await _call("alice", "secret", 6)  # PAM_PERM_DENIED
    assert resp.status == "failure"


@pytest.mark.asyncio
async def test_expired_password_is_password_change_required():
    for code in (PAM_NEW_AUTHTOK_REQD, PAM_AUTHTOK_EXPIRED):
        resp = await _call("wlanpi", "secret", code)
        assert resp.status == "password_change_required"


@pytest.mark.asyncio
async def test_pam_error_maps_to_500():
    with patch(
        "wlanpi_core.api.api_v1.endpoints.pam_api._pam_authenticate",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(HTTPException) as exc:
            await pam_authenticate(
                _request(), PAMAuthRequest(username="wlanpi", password="secret")
            )
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_empty_password_rejected_by_schema():
    with pytest.raises(ValidationError):
        PAMAuthRequest(username="wlanpi", password="")


def test_request_rejects_missing_username():
    with pytest.raises(ValidationError):
        PAMAuthRequest(username="", password="secret")


def test_password_is_secret():
    req = PAMAuthRequest(username="wlanpi", password="hunter2")
    assert "hunter2" not in repr(req)
    assert str(req.password) == "**********"
