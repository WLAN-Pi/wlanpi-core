from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from wlanpi_core.asgi import app


@pytest.fixture(scope="session", autouse=True)
def mock_wlanpi_group():
    """Mock the wlanpi group for all tests to prevent system check failures in CI."""
    mock_group = MagicMock()
    mock_group.gr_gid = 1000
    mock_group.gr_name = "wlanpi"

    with patch("grp.getgrnam") as mock_getgrnam:
        mock_getgrnam.return_value = mock_group
        yield


def test_app_startup():
    """Test that the FastAPI application starts without error."""
    with TestClient(app) as client:
        assert client is not None


def test_health_check():
    """Test basic application health via root endpoint."""
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code < 500
