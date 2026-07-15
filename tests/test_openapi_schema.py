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
    "deprecated",
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
            assert spec.get("tags") == ["deprecated"], (
                f"{path} {method} should use deprecated tag only, got {spec.get('tags')}"
            )


def test_deprecated_wlan_routes_not_under_network_tag(openapi_schema):
    paths = openapi_schema["paths"]
    for path in DEPRECATED_WLAN_PATHS:
        for method, spec in paths[path].items():
            if method.startswith("x-"):
                continue
            assert "network" not in (spec.get("tags") or []), (
                f"{path} {method} should not appear under network tag"
            )


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
        assert "200" not in post["responses"]


def test_auth_token_openapi_security(openapi_schema):
    post = openapi_schema["paths"]["/api/v1/auth/token"]["post"]
    security = post.get("security", [])
    assert {"HTTPBearer": []} not in security
    assert security == [{"HmacSignature": []}, {}]


def test_reachability_documents_targets_and_errors(openapi_schema):
    get = openapi_schema["paths"]["/api/v1/utils/reachability"]["get"]
    param_names = {p["name"] for p in get.get("parameters", [])}
    assert "targets" in param_names
    assert "400" in get["responses"]
    assert "503" in get["responses"]
    schema = get["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ReachabilityTest")


def test_speedtest_in_openapi(openapi_schema):
    get = openapi_schema["paths"]["/api/v1/utils/speedtest"]["get"]
    assert "200" in get["responses"]
    assert "503" in get["responses"]
    ref = get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/SpeedTest")


def test_canonical_wlan_scan_in_openapi(openapi_schema):
    get = openapi_schema["paths"]["/api/v1/utils/wlan/scan"]["get"]
    assert get.get("summary")
    assert "canonical" in get["summary"].lower()
    assert "422" in get["responses"]
    assert "503" in get["responses"]
    ref = get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/WlanScanResponse")
    schema = openapi_schema["components"]["schemas"]["WlanScanResponse"]
    assert schema.get("additionalProperties") is False


def test_network_config_status_typed(openapi_schema):
    get = openapi_schema["paths"]["/api/v1/network/config/status"]["get"]
    ref = get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/NetworkConfigStatus")
    assert "IwInterfaceStatus" in openapi_schema["components"]["schemas"]


def test_profiler_passphrase_optional_when_idle(openapi_schema):
    schema = openapi_schema["components"]["schemas"]["Status"]
    props = schema["properties"]
    assert "passphrase" in props
    assert "passphrase" not in schema.get("required", [])


def test_device_stats_cpu_temp_example(openapi_schema):
    schema = openapi_schema["components"]["schemas"]["DeviceStats"]
    assert schema["properties"]["cpu_temp"]["example"] == "52.0C"


def test_streaming_websocket_documented(openapi_schema):
    path = openapi_schema["paths"].get("/api/v1/streaming/capture")
    assert path is not None
    assert "get" in path
    assert path["get"]["tags"] == ["streaming"]
    assert "101" in path["get"]["responses"]


def test_hotspot_clients_documents_409(openapi_schema):
    get = openapi_schema["paths"]["/api/v1/system/hotspot/clients"]["get"]
    assert "409" in get["responses"]


def test_speedtest_documents_slow_operation(openapi_schema):
    get = openapi_schema["paths"]["/api/v1/utils/speedtest"]["get"]
    assert get.get("summary")
    assert "slow" in get["summary"].lower() or "slow" in get.get("description", "").lower()


def test_bluetooth_pair_contract(openapi_schema):
    post = openapi_schema["paths"]["/api/v1/bluetooth/pair"]["post"]
    assert "409" in post["responses"]
    assert "503" in post["responses"]

    schema = openapi_schema["components"]["schemas"]["BluetoothPairResponse"]
    status = schema["properties"]["status"]
    assert status.get("const") == "discoverable" or status.get("enum") == [
        "discoverable"
    ]
    assert "PairedDevice" not in openapi_schema["components"]["schemas"]


def test_dhcp_renew_documents_networkd_guard(openapi_schema):
    post = openapi_schema["paths"][
        "/api/v1/network/interfaces/{iface}/renew"
    ]["post"]
    assert "systemd-networkd" in post["description"]
    assert "400" in post["responses"]
    assert "409" in post["responses"]
    assert "503" in post["responses"]
