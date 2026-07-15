"""
WebSocket streaming endpoints.

See docs/API-INTEGRATION-GUIDE.md §7 for the capture command protocol.
"""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError as PydanticValidationError

from wlanpi_core.core.logging import get_logger
from wlanpi_core.streaming.connection_manager import ConnectionManager
from wlanpi_core.streaming.models import CaptureConfigurations

router = APIRouter()
log = get_logger(__name__)
manager = ConnectionManager()


@router.websocket(
    "/capture",
    name="Packet capture WebSocket",
)
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    Live WiFi packet capture over WebSocket (pcapng binary stream).

    **Protocol:** send JSON text commands; receive JSON events and binary frames.

    | Command | Payload | Effect |
    |---------|---------|--------|
    | `get_supported_frequencies` | `{}` | Returns supported channel list |
    | `configure` | `{ "interfaces": { "wlanpi0": {…} } }` | Per-interface capture config |
    | `start` | `{ "interfaces": ["wlanpi0"], "pcap_filter": "…" }` | Begin streaming |
    | `stop` | `{}` | Stop capture for this client |

    **Auth:** not enforced today — treat as privileged; REST session API will add tokens.

    **Long-running:** keep connection open for entire capture session; use `stop` before disconnect.

    **Replacement (planned):** REST `/wifi/capture/sessions` + subscriber WebSocket with token.
    """
    await manager.connect(websocket)

    try:
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

            else:
                await manager.send_message_event(
                    websocket,
                    "error",
                    "UNKNOWN_COMMAND",
                    f"Unsupported command: {command}",
                )

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        log.error(f"Unhandled error in websocket endpoint: {e!r}")
        await manager.disconnect(websocket)
