"""Fixtures for P0 API matrix tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wlanpi_core.asgi import app


@pytest.fixture(autouse=True)
def bypass_auth():
    """Matrix tests focus on handler behaviour; auth covered in test_auth."""
    from wlanpi_core.asgi import app
    from wlanpi_core.core.auth import verify_auth_wrapper

    async def _allow():
        return True

    app.dependency_overrides[verify_auth_wrapper] = _allow
    yield
    app.dependency_overrides.pop(verify_auth_wrapper, None)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {}
