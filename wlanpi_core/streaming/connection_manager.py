import asyncio
import json

from fastapi import WebSocket

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[WebSocket, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = None

    def disconnect(self, websocket: WebSocket):
        task = self.active_connections.pop(websocket, None)
        if task and not task.done():
            task.cancel()

    def start_streaming(self, websocket: WebSocket):
        task = asyncio.create_task(self._send_data(websocket))
        self.active_connections[websocket] = task

    def stop_streaming(self, websocket: WebSocket):
        task = self.active_connections.get(websocket)
        if task and not task.done():
            task.cancel()
            self.active_connections[websocket] = None

    async def _send_data(self, websocket: WebSocket):
        try:
            while True:
                data = {
                    "value": "some realtime data"
                }  # replace with actual data, e.g. response from function to get latest scan resutlts
                await websocket.send_text(json.dumps(data))
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            log.info("Streaming task cancelled")
        except Exception as e:
            log.error(f"Error during streaming: {e}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)
