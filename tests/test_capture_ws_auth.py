"""Capture WebSocket authentication and subscriber model (#141, plan P6).

The socket must authenticate with a first message carrying a core JWT;
tokens in the URL are refused outright (query strings are logged by nginx).
A running capture is a session other authenticated principals may subscribe
to read-only; only the owning socket controls it.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import wlanpi_core.api.api_v1.endpoints.streaming_api as streaming_api
from wlanpi_core.api.api_v1.endpoints.streaming_api import WS_AUTH_CLOSE_CODE, manager
from wlanpi_core.asgi import app

WS_PATH = "/api/v1/streaming/capture"


def _stub_token_manager(valid=True, did="tester"):
    result = SimpleNamespace(
        is_valid=valid,
        device_id=did if valid else None,
        payload={"did": did} if valid else None,
        error=None if valid else "invalid",
    )
    return SimpleNamespace(verify_token=AsyncMock(return_value=result))


def _assert_closed(websocket):
    with pytest.raises(WebSocketDisconnect) as exc:
        websocket.receive_json()
    assert exc.value.code == WS_AUTH_CLOSE_CODE


# --- Handshake --------------------------------------------------------------


def test_token_in_url_is_refused():
    with TestClient(app) as client:
        with client.websocket_connect(f"{WS_PATH}?token=eyJhbGci") as websocket:
            assert websocket.receive_json()["code"] == "AUTH_TOKEN_IN_URL"
            _assert_closed(websocket)
    assert manager.clients == {}


def test_first_message_must_be_auth():
    with TestClient(app) as client:
        with client.websocket_connect(WS_PATH) as websocket:
            websocket.send_json({"command": "get_supported_frequencies"})
            assert websocket.receive_json()["code"] == "AUTH_REQUIRED"
            _assert_closed(websocket)
    assert manager.clients == {}


def test_invalid_token_is_refused():
    with TestClient(app) as client:
        app.state.token_manager = _stub_token_manager(valid=False)
        with client.websocket_connect(WS_PATH) as websocket:
            websocket.send_json({"command": "auth", "token": "garbage"})
            assert websocket.receive_json()["code"] == "AUTH_FAILED"
            _assert_closed(websocket)


def test_missing_token_field_is_refused():
    with TestClient(app) as client:
        with client.websocket_connect(WS_PATH) as websocket:
            websocket.send_json({"command": "auth"})
            assert websocket.receive_json()["code"] == "AUTH_FAILED"
            _assert_closed(websocket)


def test_auth_timeout_closes_socket(monkeypatch):
    monkeypatch.setattr(streaming_api, "AUTH_TIMEOUT_SECONDS", 0.2)
    with TestClient(app) as client:
        with client.websocket_connect(WS_PATH) as websocket:
            assert websocket.receive_json()["code"] == "AUTH_TIMEOUT"
            _assert_closed(websocket)


def test_valid_token_authenticates_and_protocol_continues():
    with TestClient(app) as client:
        app.state.token_manager = _stub_token_manager(did="student-1")
        with client.websocket_connect(WS_PATH) as websocket:
            websocket.send_json({"command": "auth", "token": "e.y.J"})
            ok = websocket.receive_json()
            assert ok["code"] == "AUTH_OK"
            assert ok["data"]["did"] == "student-1"

            websocket.send_json({"command": "auth", "token": "e.y.J"})
            assert websocket.receive_json()["code"] == "ALREADY_AUTHENTICATED"

            websocket.send_json({"command": "list_sessions"})
            listing = websocket.receive_json()
            assert listing["code"] == "SESSIONS"
            assert listing["data"]["sessions"] == []

            websocket.send_json({"command": "subscribe", "session_id": "cap_none"})
            assert websocket.receive_json()["code"] == "SESSION_NOT_FOUND"
    assert manager.clients == {}


# --- Subscriber fan-out (manager unit level, mock sockets) ------------------


class _MockWS:
    """Hashable stand-in (manager keys clients by socket identity)."""

    def __init__(self):
        self.accept = AsyncMock()
        self.send_bytes = AsyncMock()
        self.send_text = AsyncMock()


def _mock_ws():
    return _MockWS()


async def _connected(mgr, did):
    ws = _mock_ws()
    await mgr.connect(ws)
    mgr.authenticate(ws, did)
    return ws


def _register_session(mgr, owner_ws, session_id, interfaces=("wlan0",)):
    client = mgr.clients[owner_ws]
    client["session_id"] = session_id
    client["interfaces"] = set(interfaces)
    client["session_config"] = {
        "interfaces": {
            iface: {"channels": [{"freq": 2412, "width": 20}], "dwell_time": 250}
            for iface in interfaces
        },
        "pcap_filter": "type mgt",
    }
    mgr.sessions[session_id] = owner_ws
    return client


@pytest.mark.asyncio
async def test_subscriber_receives_broadcast_and_stop_notification():
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    owner = await _connected(mgr, "owner-did")
    listener = await _connected(mgr, "listener-did")
    client = _register_session(mgr, owner, "cap_test")

    await mgr.subscribe(listener, "cap_test")
    assert listener in client["subscribers"]
    assert mgr.clients[listener]["subscribed_to"] == "cap_test"

    # The SUBSCRIBED event tells the listener the running config, so it is
    # not blind to what it receives.
    subscribed = [
        json.loads(c.args[0])
        for c in listener.send_text.await_args_list
    ]
    payload = next(e for e in subscribed if e["code"] == "SUBSCRIBED")
    assert payload["data"]["config"]["pcap_filter"] == "type mgt"
    assert "wlan0" in payload["data"]["config"]["interfaces"]

    await mgr._broadcast_chunk(owner, client, b"pcapng-bytes")
    owner.send_bytes.assert_awaited_once_with(b"pcapng-bytes")
    listener.send_bytes.assert_awaited_once_with(b"pcapng-bytes")

    await mgr._end_session(client, "CAPTURE_STOPPED", "Capture stopped.")
    assert mgr.sessions == {}
    assert client["subscribers"] == set()
    assert mgr.clients[listener]["subscribed_to"] is None
    # The stop notification reached the listener.
    sent = [c.args[0] for c in listener.send_text.await_args_list]
    assert any("CAPTURE_STOPPED" in payload for payload in sent)


@pytest.mark.asyncio
async def test_failing_subscriber_is_dropped_without_ending_capture():
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    owner = await _connected(mgr, "owner-did")
    dead = await _connected(mgr, "dead-did")
    client = _register_session(mgr, owner, "cap_test")

    await mgr.subscribe(dead, "cap_test")
    dead.send_bytes.side_effect = RuntimeError("gone")

    await mgr._broadcast_chunk(owner, client, b"chunk")
    assert dead not in client["subscribers"]
    assert mgr.clients[dead]["subscribed_to"] is None
    # Owner stream unaffected.
    owner.send_bytes.assert_awaited_once()


@pytest.mark.asyncio
async def test_owner_cannot_subscribe_to_own_session():
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    owner = await _connected(mgr, "owner-did")
    _register_session(mgr, owner, "cap_test")

    await mgr.subscribe(owner, "cap_test")
    sent = [c.args[0] for c in owner.send_text.await_args_list]
    assert any("SESSION_IS_OWN" in payload for payload in sent)


@pytest.mark.asyncio
async def test_subscriber_disconnect_detaches_cleanly():
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    owner = await _connected(mgr, "owner-did")
    listener = await _connected(mgr, "listener-did")
    client = _register_session(mgr, owner, "cap_test")

    await mgr.subscribe(listener, "cap_test")
    await mgr.disconnect(listener)
    assert listener not in client["subscribers"]
    assert listener not in mgr.clients
