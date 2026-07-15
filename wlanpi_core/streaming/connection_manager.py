import asyncio
import json
import re
from typing import Any, Dict

from fastapi import WebSocket

from wlanpi_core.constants import DUMPCAP_FILE, IW_FILE
from wlanpi_core.core.logging import get_logger
from wlanpi_core.utils.general import run_command_async, terminate_process_async
from wlanpi_core.streaming.models import (
    CaptureInterfaceConfig,
    CaptureStart,
    validate_capture_frequency,
    validate_capture_interface,
    validate_capture_width,
)

log = get_logger(__name__)
_IW_TIMEOUT_SEC = 5


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
            iface = validate_capture_interface(iface)
            validated = CaptureInterfaceConfig.model_validate(config)
            self.clients[websocket]["configs"][iface] = validated.model_dump()

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
            output = (
                await run_command_async(
                    [IW_FILE, "dev"],
                    timeout=_IW_TIMEOUT_SEC,
                )
            ).stdout
            interfaces = re.findall(r"Interface (wlanpi\d+)", output)

            freqs_by_iface = {}

            for iface in interfaces:
                try:
                    index = int(re.search(r"wlanpi(\d+)", iface).group(1))
                    phy = f"phy{index}"

                    chan_output = (
                        await run_command_async(
                            [IW_FILE, "phy", phy, "channels"],
                            timeout=_IW_TIMEOUT_SEC,
                        )
                    ).stdout

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
        pcap_filter: str,
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

        try:
            start = CaptureStart(
                interfaces=interfaces,
                pcap_filter=pcap_filter,
            )
        except ValueError:
            await self.send_message_event(
                websocket,
                "error",
                "CAPTURE_CONFIG_INVALID",
                "Invalid capture start configuration.",
            )
            return
        interfaces = start.interfaces
        pcap_filter = start.pcap_filter

        if (
            client["task"] and not client["task"].done()
        ) or (client["proc"] and client["proc"].returncode is None):
            await self.send_message_event(
                websocket,
                "error",
                "CAPTURE_ALREADY_RUNNING",
                "A capture is already running for this client.",
            )
            return

        if client["task"] or client["proc"] or client["channel_tasks"]:
            await self.stop_streaming(websocket, notify=False)

        missing = [i for i in interfaces if i not in client["configs"]]
        if missing:
            await self.send_message_event(
                websocket,
                "error",
                "CONFIG_MISSING",
                f"No config for: {', '.join(missing)}",
            )
            return

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
                start_new_session=True,
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
                raise
            except Exception:
                await self.send_message_event(
                    websocket,
                    "error",
                    "CAPTURE_STREAM_ERROR",
                    "Error while streaming capture data.",
                )
            finally:
                await terminate_process_async(proc)
                if client.get("proc") is proc:
                    client["proc"] = None
                if client.get("task") is asyncio.current_task():
                    client["task"] = None

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

    async def stop_streaming(self, websocket: WebSocket, notify: bool = True) -> None:
        client = self.clients.get(websocket)
        if not client:
            return

        task = client.get("task")
        proc = client.get("proc")
        channel_tasks = list(client.get("channel_tasks", {}).values())

        for channel_task in channel_tasks:
            channel_task.cancel()
        if task:
            task.cancel()

        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.debug(f"Capture streaming task shutdown failed: {e}")

        if proc:
            await terminate_process_async(proc)

        for channel_task in channel_tasks:
            try:
                await channel_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.debug(f"Channel hopping task shutdown failed: {e}")

        client["task"] = None
        client["proc"] = None
        client["channel_tasks"] = {}
        client.pop("channel_state", None)

        if notify:
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
        try:
            iface = validate_capture_interface(iface)
            freq = validate_capture_frequency(freq)
            width = validate_capture_width(width)
        except ValueError:
            return False

        cmd = [IW_FILE, "dev", iface, "set", "freq", str(freq), str(width)]

        if width >= 40:
            center_frequency = self._center_frequency(freq, width)
            if center_frequency < 0:
                return False
            cmd.append(str(center_frequency))

        try:
            result = await run_command_async(
                cmd,
                raise_on_fail=False,
                timeout=_IW_TIMEOUT_SEC,
            )
            return result.success
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
