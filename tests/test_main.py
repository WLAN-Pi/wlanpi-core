import pytest
from fastapi.testclient import TestClient
from wlanpi_core.asgi import app  

def test_app_startup():
    """Test that the FastAPI application starts without error."""
    with TestClient(app) as client:
        assert client is not None

def test_health_check():
    """Test basic application health via root endpoint."""
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code < 500
