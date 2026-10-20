"""The /api landing page lists the routes of the app that serves it."""

from fastapi.testclient import TestClient

from wlanpi_core.app import create_app


def test_landing_page_renders_app_state_endpoints():
    app = create_app(debug=False)
    app.state.endpoints = [
        {"path": "/api/v1/sample", "methods": "GET", "description": "Sample route."}
    ]

    page = TestClient(app).get("/api").text

    assert 'href="/api/v1/sample"' in page
    assert "Sample route." in page
