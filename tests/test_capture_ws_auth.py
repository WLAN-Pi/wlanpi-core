"""Capture WebSocket authentication and subscriber model (#141, plan P6).

The socket must authenticate with a first message carrying a core JWT;
tokens in the URL are refused outright (query strings are logged by nginx).
A running capture is a session other authenticated principals may subscribe
to read-only; only the owning socket controls it.
"""

import asyncio
import json
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import wlanpi_core.api.api_v1.endpoints.streaming_api as streaming_api
from wlanpi_core.api.api_v1.endpoints.streaming_api import WS_AUTH_CLOSE_CODE, manager
from wlanpi_core.asgi import app

WS_PATH = "/api/v1/streaming/capture"


def _pcapng_block(block_type, body=b""):
    body += b"\x00" * (-len(body) % 4)
    total_length = len(body) + 12
    return (
        struct.pack("<II", block_type, total_length)
        + body
        + struct.pack("<I", total_length)
    )


PCAPNG_HEADER = _pcapng_block(
    0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)
) + _pcapng_block(1, struct.pack("<HHI", 127, 0, 65535))


def _pcapng_packet(payload=b"packet"):
    body = struct.pack("<IIIII", 0, 0, 0, len(payload), len(payload)) + payload
    return _pcapng_block(6, body)


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


def test_binary_first_message_is_refused():
    with TestClient(app) as client:
        with client.websocket_connect(WS_PATH) as websocket:
            websocket.send_bytes(b"not-json")
            assert websocket.receive_json()["code"] == "AUTH_REQUIRED"
            _assert_closed(websocket)


def test_token_without_device_identity_is_refused():
    with TestClient(app) as client:
        app.state.token_manager = _stub_token_manager(did=None)
        with client.websocket_connect(WS_PATH) as websocket:
            websocket.send_json({"command": "auth", "token": "e.y.J"})
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

            websocket.send_json({"command": "subscribe", "session_id": []})
            assert websocket.receive_json()["code"] == "SESSION_NOT_FOUND"
    assert manager.clients == {}


# --- Subscriber fan-out (manager unit level, mock sockets) ------------------


class _MockWS:
    """Hashable stand-in (manager keys clients by socket identity)."""

    def __init__(self):
        self.accept = AsyncMock()
        self.close = AsyncMock()
        self.send_bytes = AsyncMock()
        self.send_text = AsyncMock()


def _mock_ws():
    return _MockWS()


def _signal_events(websocket, *codes):
    events = {code: asyncio.Event() for code in codes}

    async def send_text(payload):
        code = json.loads(payload).get("code")
        if code in events:
            events[code].set()

    websocket.send_text.side_effect = send_text
    return events


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
    client["namespace"] = "wlan_ns"
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
    received = []
    all_blocks = asyncio.Event()
    events = _signal_events(listener, "SUBSCRIBED", "CAPTURE_STOPPED")

    async def receive_block(block):
        received.append(block)
        if len(received) == 3:
            all_blocks.set()

    listener.send_bytes.side_effect = receive_block

    await mgr.subscribe(listener, "cap_test")
    subscription_task = mgr.clients[listener]["subscription_task"]
    await asyncio.wait_for(events["SUBSCRIBED"].wait(), timeout=1)
    assert listener in client["subscribers"]
    assert mgr.clients[listener]["subscribed_to"] == "cap_test"

    # The SUBSCRIBED event tells the listener the running config, so it is
    # not blind to what it receives.
    subscribed = [json.loads(c.args[0]) for c in listener.send_text.await_args_list]
    payload = next(e for e in subscribed if e["code"] == "SUBSCRIBED")
    assert payload["data"]["config"]["pcap_filter"] == "type mgt"
    assert "wlan0" in payload["data"]["config"]["interfaces"]
    # The subscriber is told which namespace the capture runs in.
    assert payload["data"]["namespace"] == "wlan_ns"

    packet = _pcapng_packet()
    stream = PCAPNG_HEADER + packet
    await mgr._broadcast_chunk(owner, client, stream)
    await asyncio.wait_for(all_blocks.wait(), timeout=1)
    owner.send_bytes.assert_awaited_once_with(stream)
    assert received == [
        PCAPNG_HEADER[:28],
        PCAPNG_HEADER[28:],
        packet,
    ]

    await mgr._end_session(client, "CAPTURE_STOPPED", "Capture stopped.")
    await asyncio.wait_for(events["CAPTURE_STOPPED"].wait(), timeout=1)
    await subscription_task
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
    subscription_task = mgr.clients[dead]["subscription_task"]
    dead.send_bytes.side_effect = RuntimeError("gone")

    await mgr._broadcast_chunk(owner, client, PCAPNG_HEADER)
    await subscription_task
    assert dead not in client["subscribers"]
    assert mgr.clients[dead]["subscribed_to"] is None
    # Owner stream unaffected.
    owner.send_bytes.assert_awaited_once()


@pytest.mark.asyncio
async def test_late_subscriber_gets_header_then_complete_packet_blocks():
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager()
    owner = await _connected(mgr, "owner-did")
    listener = await _connected(mgr, "listener-did")
    client = _register_session(mgr, owner, "cap_test")
    first_packet = _pcapng_packet(b"first")
    received = []
    all_blocks = asyncio.Event()

    async def receive_block(block):
        received.append(block)
        if len(received) == 2:
            all_blocks.set()

    listener.send_bytes.side_effect = receive_block

    await mgr._broadcast_chunk(owner, client, PCAPNG_HEADER + first_packet)
    await mgr.subscribe(listener, "cap_test")
    subscription_task = mgr.clients[listener]["subscription_task"]

    second_packet = _pcapng_packet(b"second")
    split = len(second_packet) // 2
    await mgr._broadcast_chunk(owner, client, second_packet[:split])
    await mgr._broadcast_chunk(owner, client, second_packet[split:])
    await asyncio.wait_for(all_blocks.wait(), timeout=1)

    assert received == [PCAPNG_HEADER, second_packet]
    await mgr._end_session(client, "CAPTURE_ENDED", "Capture ended.")
    await subscription_task


@pytest.mark.asyncio
async def test_slow_subscriber_is_dropped_without_blocking_owner(monkeypatch):
    from wlanpi_core.streaming import connection_manager
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    monkeypatch.setattr(connection_manager, "_SUBSCRIBER_QUEUE_BLOCKS", 2)
    mgr = ConnectionManager()
    owner = await _connected(mgr, "owner-did")
    slow = await _connected(mgr, "slow-did")
    client = _register_session(mgr, owner, "cap_test")
    await mgr.subscribe(slow, "cap_test")
    subscription_task = mgr.clients[slow]["subscription_task"]

    stream = PCAPNG_HEADER + _pcapng_packet()
    await mgr._broadcast_chunk(owner, client, stream)
    await subscription_task

    assert slow not in client["subscribers"]
    assert mgr.clients[slow]["subscribed_to"] is None
    owner.send_bytes.assert_awaited_once_with(stream)
    slow.close.assert_awaited_once_with(
        code=connection_manager._SLOW_SUBSCRIBER_CLOSE_CODE,
        reason="Capture subscriber cannot keep up.",
    )


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
async def test_capture_owner_cannot_subscribe_to_another_session():
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager()
    first_owner = await _connected(mgr, "first-owner")
    second_owner = await _connected(mgr, "second-owner")
    first_client = _register_session(mgr, first_owner, "cap_first")
    second_client = _register_session(mgr, second_owner, "cap_second")

    await mgr.subscribe(first_owner, "cap_second")

    assert first_owner not in second_client["subscribers"]
    assert first_client["subscribed_to"] is None
    sent = [call.args[0] for call in first_owner.send_text.await_args_list]
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


@pytest.mark.asyncio
async def test_old_session_end_does_not_clear_new_subscription():
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager()
    old_owner = await _connected(mgr, "old-owner")
    new_owner = await _connected(mgr, "new-owner")
    listener = await _connected(mgr, "listener")
    old_client = _register_session(mgr, old_owner, "cap_old")
    new_client = _register_session(mgr, new_owner, "cap_new")
    subscribed = []
    first_subscription = asyncio.Event()
    second_subscription = asyncio.Event()
    binary_send_started = asyncio.Event()

    async def record_event(payload):
        code = json.loads(payload).get("code")
        if code == "SUBSCRIBED":
            subscribed.append(code)
            if len(subscribed) == 1:
                first_subscription.set()
            else:
                second_subscription.set()

    async def block_binary(_):
        binary_send_started.set()
        await asyncio.Event().wait()

    listener.send_text.side_effect = record_event
    listener.send_bytes.side_effect = block_binary
    await mgr.subscribe(listener, "cap_old")
    await asyncio.wait_for(first_subscription.wait(), timeout=1)
    await mgr._broadcast_chunk(old_owner, old_client, PCAPNG_HEADER)
    await asyncio.wait_for(binary_send_started.wait(), timeout=1)

    await mgr._end_session(old_client, "CAPTURE_ENDED", "Capture ended.")
    await mgr.subscribe(listener, "cap_new")
    new_subscription_task = mgr.clients[listener]["subscription_task"]
    await asyncio.wait_for(second_subscription.wait(), timeout=1)

    assert mgr.clients[listener]["subscribed_to"] == "cap_new"
    assert listener in new_client["subscribers"]
    sent_codes = [
        json.loads(call.args[0])["code"] for call in listener.send_text.await_args_list
    ]
    assert sent_codes == ["SUBSCRIBED", "SUBSCRIBED"]
    await mgr._end_session(new_client, "CAPTURE_ENDED", "Capture ended.")
    await new_subscription_task


# --- Namespace awareness (#141 baseline: capture must run in the adapter's ns)


def _status(**ns_ifaces):
    """Build a network_config.status()-shaped dict: {ns_or_root: {iface: {...}}}."""
    return {
        ns: {iface: {"type": "monitor"} for iface in ifaces}
        for ns, ifaces in ns_ifaces.items()
    }


@pytest.mark.asyncio
async def test_resolve_namespace_finds_named_namespace(mocker):
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    mocker.patch(
        "wlanpi_core.streaming.connection_manager.network_config.status",
        return_value=_status(root={}, wlan_ns=["wlanpi0"]),
    )
    ns, err = await mgr._resolve_namespace(["wlanpi0"])
    assert err is None
    assert ns == "wlan_ns"


@pytest.mark.asyncio
async def test_resolve_namespace_root_is_none(mocker):
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    mocker.patch(
        "wlanpi_core.streaming.connection_manager.network_config.status",
        return_value=_status(root=["wlanpi0"]),
    )
    ns, err = await mgr._resolve_namespace(["wlanpi0"])
    assert err is None and ns is None


@pytest.mark.asyncio
async def test_resolve_namespace_missing_interface_errors(mocker):
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    mocker.patch(
        "wlanpi_core.streaming.connection_manager.network_config.status",
        return_value=_status(root=["wlanpi9"]),
    )
    ns, err = await mgr._resolve_namespace(["wlanpi0"])
    assert ns is None and "not found" in err


@pytest.mark.asyncio
async def test_resolve_namespace_split_across_namespaces_errors(mocker):
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    mocker.patch(
        "wlanpi_core.streaming.connection_manager.network_config.status",
        return_value=_status(ns_a=["wlanpi0"], ns_b=["wlanpi1"]),
    )
    ns, err = await mgr._resolve_namespace(["wlanpi0", "wlanpi1"])
    assert ns is None and "multiple namespaces" in err


def test_ns_prefix_wraps_named_namespace_only():
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    assert ConnectionManager._ns_prefix(None) == []
    assert ConnectionManager._ns_prefix("wlan_ns") == [
        "ip",
        "netns",
        "exec",
        "wlan_ns",
    ]


@pytest.mark.asyncio
async def test_set_channel_runs_in_namespace(mocker):
    from wlanpi_core.models.command_result import CommandResult
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    run = mocker.patch(
        "wlanpi_core.streaming.connection_manager.run_command_async",
        return_value=CommandResult("", "", 0),
    )
    assert await mgr._set_channel("wlanpi0", 2412, 20, "wlan_ns") is None
    cmd = run.call_args.args[0]
    assert cmd[:4] == ["ip", "netns", "exec", "wlan_ns"]
    assert "set" in cmd and "freq" in cmd


@pytest.mark.asyncio
async def test_subscriber_stop_is_rejected_without_ending_owner_session():
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager.__new__(ConnectionManager)
    mgr.__init__()
    owner = await _connected(mgr, "owner-did")
    listener = await _connected(mgr, "listener-did")
    _register_session(mgr, owner, "cap_test")
    events = _signal_events(listener, "SUBSCRIBED")
    await mgr.subscribe(listener, "cap_test")
    await asyncio.wait_for(events["SUBSCRIBED"].wait(), timeout=1)

    await mgr.stop_streaming(listener)

    # Owner's session survives untouched.
    assert "cap_test" in mgr.sessions
    assert mgr.sessions["cap_test"] is owner
    assert mgr.clients[owner]["session_id"] == "cap_test"
    assert mgr.clients[listener]["subscribed_to"] == "cap_test"
    sent = [c.args[0] for c in listener.send_text.await_args_list]
    assert any("SUBSCRIBER_READ_ONLY" in payload for payload in sent)
    await mgr.disconnect(listener)
    await mgr._end_session(mgr.clients[owner], "CAPTURE_ENDED", "Capture ended.")


@pytest.mark.asyncio
async def test_subscriber_cannot_start_another_capture(mocker):
    from wlanpi_core.streaming import connection_manager
    from wlanpi_core.streaming.connection_manager import ConnectionManager

    mgr = ConnectionManager()
    owner = await _connected(mgr, "owner-did")
    listener = await _connected(mgr, "listener-did")
    _register_session(mgr, owner, "cap_test")
    events = _signal_events(listener, "SUBSCRIBED")
    await mgr.subscribe(listener, "cap_test")
    await asyncio.wait_for(events["SUBSCRIBED"].wait(), timeout=1)
    create_process = mocker.patch.object(
        connection_manager.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(),
    )

    await mgr.start_streaming(listener, ["wlanpi1"], "")

    create_process.assert_not_awaited()
    sent = [call.args[0] for call in listener.send_text.await_args_list]
    assert any("SUBSCRIBER_READ_ONLY" in payload for payload in sent)
    await mgr.disconnect(listener)
    await mgr._end_session(mgr.clients[owner], "CAPTURE_ENDED", "Capture ended.")
