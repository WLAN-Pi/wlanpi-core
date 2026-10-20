from fastapi.testclient import TestClient

from wlanpi_core.asgi import app


def test_app_startup():
    with TestClient(app) as client:
        assert client is not None


def test_health_check():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code < 500
