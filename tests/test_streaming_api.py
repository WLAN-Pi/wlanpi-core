"""Behavioral tests for the packet-capture WebSocket protocol."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from wlanpi_core.api.api_v1.endpoints.streaming_api import manager
from wlanpi_core.asgi import app


def _stub_token_manager():
    result = SimpleNamespace(
        is_valid=True, device_id="proto-test", payload={"did": "proto-test"}
    )
    return SimpleNamespace(verify_token=AsyncMock(return_value=result))


def test_capture_websocket_reports_protocol_errors_and_disconnects_cleanly():
    with TestClient(app) as client:
        app.state.token_manager = _stub_token_manager()
        with client.websocket_connect("/api/v1/streaming/capture") as websocket:
            websocket.send_json({"command": "auth", "token": "e.y.J"})
            assert websocket.receive_json()["code"] == "AUTH_OK"

            websocket.send_text("{")
            assert websocket.receive_json()["code"] == "INVALID_JSON"

            websocket.send_json({"command": "configure", "interfaces": {}})
            assert websocket.receive_json()["code"] == "CONFIG_INVALID"

            websocket.send_json({"command": "not-a-command"})
            assert websocket.receive_json()["code"] == "UNKNOWN_COMMAND"

    assert manager.clients == {}
    assert manager.interface_owners == {}
