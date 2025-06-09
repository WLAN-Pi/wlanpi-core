import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from wlanpi_core.streaming.connection_manager import ConnectionManager

router = APIRouter()

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            response = await websocket.receive_text()
            try:
                data = json.loads(response)
            except:
                log.error("Received data was invalid JSON.")
                await websocket.send_text("Invalid JSON")
                continue

            command = data.get("command")
            if command == "start":
                manager.start_streaming(websocket)
                await websocket.send_text("Started streaming.")
            elif command == "stop":
                manager.stop_streaming(websocket)
                await websocket.send_text("Stopped streaming.")
            else:
                await websocket.send_text("Unknown command")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        manager.disconnect(websocket)
