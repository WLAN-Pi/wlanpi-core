import asyncio
import json
import re
import subprocess
from typing import Any, Dict

from fastapi import WebSocket

from wlanpi_core.constants import DUMPCAP_FILE, IW_FILE
from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class ConnectionManager:
    def __init__(self):
        self.clients: Dict[WebSocket, Dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket) -> None:
        self.clients[websocket] = {
            "configs": {},
            "proc": None,
            "task": None,
            "channel_tasks": {},
        }
        await websocket.accept()

    def configure(self, websocket: WebSocket, iface: str, config: dict) -> None:
        if websocket in self.clients:
            self.clients[websocket]["configs"][iface] = config

    async def disconnect(self, websocket: WebSocket) -> None:
        try:
            await self.stop_streaming(websocket)
        except Exception as e:
            log.warning(f"disconnect() failed: {e!r}")
        self.clients.pop(websocket, None)

    async def send_event(
        self, websocket: WebSocket, event_type: str, code: str, data: dict
    ) -> None:
        try:
            await websocket.send_text(
                json.dumps(
                    {"type": "event", "event": event_type, "code": code, "data": data}
                )
            )
        except RuntimeError:
            pass
        except Exception as e:
            log.debug(f"send_event() failed: {e!r}")

    async def send_message_event(
        self, websocket: WebSocket, event_type: str, code: str, message: str
    ) -> None:
        await self.send_event(websocket, event_type, code, {"message": message})

    async def send_supported_frequencies(self, websocket: WebSocket) -> None:
        try:
            output = subprocess.check_output([IW_FILE, "dev"], encoding="utf-8")
            interfaces = re.findall(r"Interface (wlanpi\d+)", output)

            freqs_by_iface = {}

            for iface in interfaces:
                try:
                    index = int(re.search(r"wlanpi(\d+)", iface).group(1))
                    phy = f"phy{index}"

                    chan_output = subprocess.check_output(
                        [IW_FILE, "phy", phy, "channels"], encoding="utf-8"
                    )

                    freqs = []
                    for line in chan_output.splitlines():
                        line = line.strip()
                        if "(disabled)" in line:
                            continue
                        match = re.match(r"\* (\d+) MHz", line)
                        if match:
                            freqs.append(int(match.group(1)))

                    freqs_by_iface[iface] = sorted(freqs)
                except Exception:
                    freqs_by_iface[iface] = []

            await self.send_event(
                websocket, "frequencies", "SUPPORTED_FREQUENCIES", freqs_by_iface
            )
        except Exception as e:
            await self.send_message_event(
                websocket,
                "error",
                "FREQ_FETCH_FAILED",
                f"Failed to fetch supported frequencies: {e}",
            )

    async def start_streaming(
        self,
        websocket: WebSocket,
        interfaces: list[str],
        pcap_filter: str | None = None,
    ) -> None:
        client = self.clients.get(websocket)
        if not client:
            await self.send_message_event(
                websocket,
                "error",
                "CLIENT_NOT_FOUND",
                "WebSocket client not registered.",
            )
            return

        missing = [i for i in interfaces if i not in client["configs"]]
        if missing:
            await self.send_message_event(
                websocket,
                "error",
                "CONFIG_MISSING",
                f"No config for: {', '.join(missing)}",
            )

        for iface in interfaces:
            config = client["configs"].get(iface)
            if not config:
                continue
            channels = config.get("channels", [])
            if channels:
                first = channels[0]
                freq = first.get("freq")
                width = first.get("width")
                if freq and width:
                    success = await self._set_channel(iface, freq, width)
                    if not success:
                        await self.send_message_event(
                            websocket,
                            "error",
                            "CHANNEL_SET_FAILED",
                            f"Could not set initial channel for {iface}",
                        )

        args = [DUMPCAP_FILE]
        for iface in interfaces:
            args += ["-i", iface]
        if pcap_filter:
            args += ["-f", pcap_filter]
        args += ["-q", "-t", "-w", "-"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception as e:
            log.warning(f"Failed to start capture process: {e!r}")
            await self.send_message_event(
                websocket, "error", "CAPTURE_START_FAILED", "Failed to start capture."
            )
            return

        async def stream() -> None:
            try:
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    await websocket.send_bytes(chunk)
                await self.send_message_event(
                    websocket, "status", "CAPTURE_ENDED", "Capture ended."
                )
            except asyncio.CancelledError:
                proc.terminate()
                await proc.wait()
            except Exception:
                await self.send_message_event(
                    websocket,
                    "error",
                    "CAPTURE_STREAM_ERROR",
                    "Error while streaming capture data.",
                )

        client["proc"] = proc
        client["task"] = asyncio.create_task(stream())
        client["channel_tasks"] = {}

        for iface in interfaces:
            config = client["configs"].get(iface)
            if not config:
                continue
            dwell = config.get("dwell_time", 100)
            channels = config.get("channels", [])
            if channels:
                task = asyncio.create_task(
                    self._hop_channels(websocket, iface, channels, dwell)
                )
                client["channel_tasks"][iface] = task

        await self.send_message_event(
            websocket,
            "status",
            "CAPTURE_STARTED",
            f"Started capture on {', '.join(interfaces)}",
        )

    async def stop_streaming(self, websocket: WebSocket) -> None:
        client = self.clients.get(websocket)
        if not client:
            return

        if client["task"]:
            client["task"].cancel()
            try:
                await client["task"]
            except asyncio.CancelledError:
                pass
            client["task"] = None

        if client["proc"]:
            try:
                client["proc"].terminate()
                await client["proc"].wait()
            except ProcessLookupError:
                pass
            except Exception as e:
                log.debug(f"Capture process termination failed: {e}")
            client["proc"] = None

        for task in client.get("channel_tasks", {}).values():
            task.cancel()
        for task in client["channel_tasks"].values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        client["channel_tasks"] = {}
        client.pop("channel_state", None)

        try:
            await self.send_message_event(
                websocket, "status", "CAPTURE_STOPPED", "Capture stopped."
            )
        except Exception:
            pass

    async def _hop_channels(
        self, websocket: WebSocket, iface: str, channels: list, dwell_time_ms: int
    ) -> None:
        async def apply_channel(ch: dict) -> None:
            freq = ch.get("freq")
            width = ch.get("width")

            if freq and width:
                success = await self._set_channel(iface, freq, width)
                if success:
                    await self.send_message_event(
                        websocket,
                        "info",
                        "CHANNEL_SET",
                        f"{iface}: {freq} MHz / {width} MHz",
                    )
                else:
                    await self.send_message_event(
                        websocket,
                        "error",
                        "CHANNEL_SET_FAILED",
                        f"{iface}: failed to set {freq} MHz / {width} MHz",
                    )

        try:
            await self.send_message_event(
                websocket, "info", "CHANNEL_LIST_STARTED", f"Hopping on {iface}"
            )

            if not channels:
                return

            if len(channels) == 1:
                await apply_channel(channels[0])
                return

            while True:
                for ch in channels:
                    await apply_channel(ch)
                    await asyncio.sleep(dwell_time_ms / 1000)

        except asyncio.CancelledError:
            return
        except Exception:
            await self.send_message_event(
                websocket, "error", "CHANNEL_HOP_ERROR", f"{iface} hopping failed."
            )

    async def _set_channel(self, iface: str, freq: int, width: int) -> bool:
        cmd = [IW_FILE, "dev", iface, "set", "freq", str(freq), str(width)]

        if width >= 40:
            cmd.append(str(self._center_frequency(freq, width)))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False

    def _center_frequency(self, freq: int, channel_width: int) -> int:
        def compute_center(start: int, span: int) -> int:
            return ((start * 2) + span) // 2

        def match_range(
            freq: int, base: int, limit: int, step: int, span: int
        ) -> int | None:
            for start in range(base, limit + 1, step):
                if start <= freq <= start + span:
                    return compute_center(start, span)
            return None

        if channel_width == 20:
            return freq

        if channel_width == 40:
            return (
                match_range(freq, 5180, 5700, 40, 20)
                or {5745: 5755, 5785: 5795, 5825: 5835, 5865: 5875}.get(freq)
                or match_range(freq, 5955, 7075, 40, 20)
                or -1
            )

        if channel_width == 80:
            return (
                match_range(freq, 5180, 5660, 80, 60)
                or {5745: 5775, 5825: 5855}.get(freq)
                or match_range(freq, 5955, 7055, 80, 60)
                or -1
            )

        if channel_width == 160:
            return (
                match_range(freq, 5180, 5500, 160, 140)
                or {5745: 5815}.get(freq)
                or match_range(freq, 5955, 6915, 160, 140)
                or -1
            )

        return -1
