"""
WebSocket streaming endpoints.

See docs/API-INTEGRATION-GUIDE.md §7 for the capture command protocol.
"""
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError as PydanticValidationError

from wlanpi_core.core.logging import get_logger
from wlanpi_core.streaming.connection_manager import ConnectionManager
from wlanpi_core.streaming.models import CaptureConfigurations

router = APIRouter()
log = get_logger(__name__)
manager = ConnectionManager()

#: Close code for authentication failures (WebSocket has no HTTP 401).
WS_AUTH_CLOSE_CODE = 4401
#: Seconds a fresh connection has to present its auth message.
AUTH_TIMEOUT_SECONDS = 10.0


async def _reject(websocket: WebSocket, code: str, message: str) -> None:
    await manager.send_message_event(websocket, "error", code, message)
    try:
        await websocket.close(code=WS_AUTH_CLOSE_CODE)
    except RuntimeError:
        pass
    await manager.disconnect(websocket)


async def _authenticate(websocket: WebSocket) -> bool:
    """First-message auth (#141): the first frame must be
    {"command": "auth", "token": "<core JWT>"} within AUTH_TIMEOUT_SECONDS.

    Tokens are never accepted in the URL: query strings end up in proxy and
    access logs, so a ?token=... connection is refused outright to keep the
    unsafe pattern from taking root.
    """
    if "token" in websocket.query_params:
        await _reject(
            websocket,
            "AUTH_TOKEN_IN_URL",
            "Tokens are not accepted in the URL (it is logged); "
            "send {\"command\": \"auth\", \"token\": ...} as the first message.",
        )
        return False

    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS
        )
        data = json.loads(raw)
    except asyncio.TimeoutError:
        await _reject(
            websocket, "AUTH_TIMEOUT", "No auth message received in time."
        )
        return False
    except json.JSONDecodeError:
        await _reject(websocket, "AUTH_REQUIRED", "First message must be valid JSON auth.")
        return False

    if not isinstance(data, dict) or data.get("command") != "auth":
        await _reject(
            websocket,
            "AUTH_REQUIRED",
            "Authenticate first: {\"command\": \"auth\", \"token\": ...}.",
        )
        return False

    token = data.get("token")
    if not isinstance(token, str) or not token:
        await _reject(websocket, "AUTH_FAILED", "Auth message carries no token.")
        return False

    try:
        result = await websocket.app.state.token_manager.verify_token(token)
    except Exception:
        log.exception("Capture WS token verification errored")
        await _reject(websocket, "AUTH_FAILED", "Token verification failed.")
        return False

    if not result.is_valid:
        await _reject(websocket, "AUTH_FAILED", "Token verification failed.")
        return False

    did = result.device_id or (result.payload or {}).get("did")
    manager.authenticate(websocket, did)
    await manager.send_event(websocket, "status", "AUTH_OK", {"did": did})
    return True


@router.websocket(
    "/capture",
    name="Packet capture WebSocket",
)
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    Live Wi-Fi packet capture over WebSocket (pcapng binary stream).

    **Protocol:** send JSON text commands; receive JSON events and binary frames.

    | Command | Payload | Effect |
    |---------|---------|--------|
    | `get_supported_frequencies` | `{}` | Returns supported channel list |
    | `configure` | `{ "interfaces": { "wlanpi0": {…} } }` | Per-interface capture config |
    | `start` | `{ "interfaces": ["wlanpi0"], "pcap_filter": "…" }` | Begin streaming |
    | `stop` | `{}` | Stop capture for this client |

    **Auth:** required. The first message must be
    `{ "command": "auth", "token": "<core JWT>" }` (within 10s); anything else,
    an invalid token, or a `?token=` query parameter closes the socket with
    code 4401. All later commands run as the authenticated principal (`did`).

    **Sessions & subscribers:** `start` returns a `session_id` in the
    `CAPTURE_STARTED` event. Any other authenticated connection may
    `{ "command": "subscribe", "session_id": … }` to receive the same binary
    stream read-only (`list_sessions` enumerates running captures); only the
    owning connection can `configure`/`stop`. `unsubscribe` detaches.

    **Long-running:** keep connection open for entire capture session; use `stop` before disconnect.

    **Replacement (planned):** REST `/wifi/capture/sessions` + subscriber WebSocket with token.
    """
    await manager.connect(websocket)

    try:
        if not await _authenticate(websocket):
            return

        while True:
            try:
                msg = await websocket.receive_text()
                data = json.loads(msg)
            except json.JSONDecodeError:
                await manager.send_message_event(
                    websocket,
                    "error",
                    "INVALID_JSON",
                    "Received data is not valid JSON.",
                )
                continue

            if not isinstance(data, dict):
                await manager.send_message_event(
                    websocket,
                    "error",
                    "COMMAND_INVALID",
                    "Capture command must be a JSON object.",
                )
                continue

            command = data.get("command")

            if command == "get_supported_frequencies":
                await manager.send_supported_frequencies(websocket)

            elif command == "configure":
                configs = data.get("interfaces")
                try:
                    validated_configs = CaptureConfigurations.model_validate(configs)
                except PydanticValidationError:
                    await manager.send_message_event(
                        websocket,
                        "error",
                        "CONFIG_INVALID",
                        "Invalid capture interface configuration.",
                    )
                else:
                    for iface, config in validated_configs.root.items():
                        manager.configure(websocket, iface, config)
                    await manager.send_message_event(
                        websocket,
                        "config",
                        "CONFIG_APPLIED",
                        f"Configured: {', '.join(validated_configs.root.keys())}",
                    )

            elif command == "start":
                interfaces = data.get("interfaces", [])
                pcap_filter = data.get("pcap_filter")
                await manager.start_streaming(websocket, interfaces, pcap_filter)

            elif command == "stop":
                await manager.stop_streaming(websocket)

            elif command == "subscribe":
                await manager.subscribe(websocket, data.get("session_id"))

            elif command == "unsubscribe":
                await manager.unsubscribe(websocket)

            elif command == "list_sessions":
                await manager.send_session_list(websocket)

            elif command == "auth":
                await manager.send_message_event(
                    websocket,
                    "status",
                    "ALREADY_AUTHENTICATED",
                    "This connection is already authenticated.",
                )

            else:
                await manager.send_message_event(
                    websocket,
                    "error",
                    "UNKNOWN_COMMAND",
                    f"Unsupported command: {command}",
                )

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except RuntimeError as e:
        # Starlette raises "WebSocket is not connected" when the peer closes
        # mid-operation - a disconnect race, not a server fault. Log at debug
        # so a genuine RuntimeError is still traceable without noise.
        log.debug(f"WebSocket closed mid-operation: {e!r}")
        await manager.disconnect(websocket)
    except Exception as e:
        log.error(f"Unhandled error in websocket endpoint: {e!r}")
        await manager.disconnect(websocket)
