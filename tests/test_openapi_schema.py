"""OpenAPI schema sanity checks for Swagger / MCP accuracy."""
from __future__ import annotations

import pytest

from wlanpi_core.app import create_app

DEPRECATED_WLAN_PATHS = {
    "/api/v1/network/wlan/getInterfaces",
    "/api/v1/network/wlan/scan",
    "/api/v1/network/wlan/set-dbus",
    "/api/v1/network/wlan/set",
    "/api/v1/network/wlan/getConnected",
}

EXPECTED_TAGS = {
    "authentication",
    "system",
    "network",
    "network_config",
    "network_information",
    "wifi",
    "device utils",
    "bluetooth",
    "profiler",
    "streaming",
}


@pytest.fixture
def openapi_schema():
    app = create_app(debug=False)
    return app.openapi()


def test_openapi_has_external_docs(openapi_schema):
    assert "externalDocs" in openapi_schema
    assert "API-INTEGRATION-GUIDE" in openapi_schema["externalDocs"]["url"]


def test_openapi_tags_cover_all_routers(openapi_schema):
    tag_names = {tag["name"] for tag in openapi_schema.get("tags", [])}
    assert EXPECTED_TAGS.issubset(tag_names)


def test_deprecated_wlan_routes_marked(openapi_schema):
    paths = openapi_schema["paths"]
    for path in DEPRECATED_WLAN_PATHS:
        assert path in paths, f"missing path {path}"
        methods = paths[path]
        for method, spec in methods.items():
            if method.startswith("x-"):
                continue
            assert spec.get("deprecated") is True, f"{path} {method} not deprecated"


def test_auth_token_has_response_schema(openapi_schema):
    post = openapi_schema["paths"]["/api/v1/auth/token"]["post"]
    assert "200" in post["responses"]
    content = post["responses"]["200"]["content"]["application/json"]["schema"]
    assert "$ref" in content
    assert content["$ref"].endswith("/Token")


def test_gone_endpoints_document_410(openapi_schema):
    for path in (
        "/api/v1/network/wlan/set-dbus",
        "/api/v1/network/wlan/set",
    ):
        post = openapi_schema["paths"][path]["post"]
        assert "410" in post["responses"]


def test_hotspot_clients_documents_409(openapi_schema):
    get = openapi_schema["paths"]["/api/v1/system/hotspot/clients"]["get"]
    assert "409" in get["responses"]


def test_speedtest_documents_slow_operation(openapi_schema):
    get = openapi_schema["paths"]["/api/v1/utils/speedtest"]["get"]
    assert get.get("summary")
    assert "slow" in get["summary"].lower() or "slow" in get.get("description", "").lower()
