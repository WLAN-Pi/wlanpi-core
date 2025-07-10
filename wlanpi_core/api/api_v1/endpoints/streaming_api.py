import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from wlanpi_core.core.logging import get_logger
from wlanpi_core.streaming.connection_manager import ConnectionManager

router = APIRouter()
log = get_logger(__name__)
manager = ConnectionManager()


@router.websocket("/capture")
async def websocket_endpoint(websocket: WebSocket) -> None:
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

            command = data.get("command")

            if command == "get_supported_frequencies":
                await manager.send_supported_frequencies(websocket)

            elif command == "configure":
                configs = data.get("interfaces")
                if isinstance(configs, dict):
                    for iface, config in configs.items():
                        manager.configure(websocket, iface, config)
                    await manager.send_message_event(
                        websocket,
                        "config",
                        "CONFIG_APPLIED",
                        f"Configured: {', '.join(configs.keys())}",
                    )
                else:
                    await manager.send_message_event(
                        websocket,
                        "error",
                        "CONFIG_INVALID",
                        "Expected 'interfaces' to be a dictionary.",
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
