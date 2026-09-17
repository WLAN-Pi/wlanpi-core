"""WebSocket connection manager for the packet capture stream."""

import asyncio
import json
import re
import secrets
from typing import Any

from fastapi import WebSocket

from wlanpi_core.constants import DUMPCAP_FILE, IW_FILE
from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.streaming.models import (
    CaptureInterfaceConfig,
    CaptureStart,
    validate_capture_frequency,
    validate_capture_interface,
    validate_capture_width,
)
from wlanpi_core.utils import network_config
from wlanpi_core.utils.general import run_command_async, terminate_process_async
from wlanpi_core.utils.validation import validate_namespace_name
from wlanpi_core.wlan.scan import iter_adapters

log = get_logger(__name__)
_IW_TIMEOUT_SEC = 5
_SUBSCRIBER_SEND_TIMEOUT_SEC = 1.0
_SUBSCRIBER_QUEUE_BLOCKS = 128
_SLOW_SUBSCRIBER_CLOSE_CODE = 1013
_PCAPNG_SECTION_HEADER = b"\x0a\x0d\x0d\x0a"
_PCAPNG_PACKET_BLOCK_TYPES = {0x00000002, 0x00000003, 0x00000006}


class ConnectionManager:
    """Manage WebSocket clients, sessions, and capture processes."""

    def __init__(self) -> None:
        self.clients: dict[WebSocket, dict[str, Any]] = {}
        self.interface_owners: dict[str, WebSocket] = {}
        # Running captures by session id -> owning WebSocket. Sessions exist
        # so other authenticated principals can subscribe read-only (#141).
        self.sessions: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a connection and register its client state."""
        await websocket.accept()
        self.clients[websocket] = {
            "configs": {},
            "proc": None,
            "task": None,
            "channel_tasks": {},
            "interfaces": set(),
            "did": None,
            "session_id": None,
            "session_config": None,
            "namespace": None,
            "subscribers": set(),
            "subscribed_to": None,
            "session_end": None,
            "pcapng_buffer": bytearray(),
            "pcapng_header": bytearray(),
            "pcapng_endian": None,
            "pcapng_header_complete": False,
            "subscription_queue": None,
            "subscription_task": None,
            "subscription_closing": False,
        }

    def authenticate(self, websocket: WebSocket, did: str) -> None:
        """Record the verified principal for this socket.

        Commands are only dispatched after this is set (first-message auth in
        the endpoint).
        """
        client = self.clients.get(websocket)
        if client is not None:
            client["did"] = did

    def is_authenticated(self, websocket: WebSocket) -> bool:
        """Return whether the socket is authenticated."""
        client = self.clients.get(websocket)
        return bool(client and client.get("did"))

    def _claim_interfaces(
        self, websocket: WebSocket, interfaces: list[str]
    ) -> list[str]:
        """Atomically claim capture interfaces for one WebSocket client."""
        conflicts = []
        for iface in interfaces:
            owner = self.interface_owners.get(iface)
            if owner is not None and owner is not websocket:
                conflicts.append(iface)
        conflicts = sorted(conflicts)
        if conflicts:
            return conflicts

        client = self.clients[websocket]
        claimed = set(interfaces)
        for iface in claimed:
            self.interface_owners[iface] = websocket
        client["interfaces"] = claimed
        return []

    def _release_interfaces(self, websocket: WebSocket) -> None:
        client = self.clients.get(websocket)
        if not client:
            return
        for iface in client.get("interfaces", set()):
            if self.interface_owners.get(iface) is websocket:
                self.interface_owners.pop(iface, None)
        client["interfaces"] = set()

    def _clear_subscription(
        self, websocket: WebSocket, expected_session: str | None = None
    ) -> asyncio.Task[Any] | None:
        client = self.clients.get(websocket)
        if not client:
            return None
        session_id = client.get("subscribed_to")
        if expected_session is not None and session_id != expected_session:
            return None
        client["subscribed_to"] = None
        client["subscription_queue"] = None
        client["subscription_closing"] = False
        task = client.get("subscription_task")
        client["subscription_task"] = None
        if session_id:
            owner_ws = self.sessions.get(session_id)
            if owner_ws is not None:
                owner_client = self.clients.get(owner_ws)
                if owner_client:
                    owner_client["subscribers"].discard(websocket)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        return task

    async def _detach_subscriber(self, websocket: WebSocket) -> None:
        task = self._clear_subscription(websocket)
        if task is None or task is asyncio.current_task():
            return
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.debug("Capture subscription task shutdown failed: %s", exc)

    async def _send_subscription(
        self,
        websocket: WebSocket,
        session_id: str,
        queue: asyncio.Queue[tuple[str, Any]],
    ) -> None:
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "done":
                    return
                if kind == "close":
                    code, reason = payload
                    await asyncio.wait_for(
                        websocket.close(code=code, reason=reason),
                        timeout=_SUBSCRIBER_SEND_TIMEOUT_SEC,
                    )
                    return
                if kind == "event":
                    send = websocket.send_text(payload)
                else:
                    send = websocket.send_bytes(payload)
                await asyncio.wait_for(
                    send,
                    timeout=_SUBSCRIBER_SEND_TIMEOUT_SEC,
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            try:
                await asyncio.wait_for(
                    websocket.close(
                        code=_SLOW_SUBSCRIBER_CLOSE_CODE,
                        reason="Capture subscriber cannot keep up.",
                    ),
                    timeout=_SUBSCRIBER_SEND_TIMEOUT_SEC,
                )
            except Exception:
                pass
        except Exception:
            pass
        finally:
            self._clear_subscription(websocket, session_id)

    @staticmethod
    def _close_subscription_queue(client: dict[str, Any]) -> None:
        queue = client.get("subscription_queue")
        if queue is None or client.get("subscription_closing"):
            return
        client["subscription_closing"] = True
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(
            (
                "close",
                (_SLOW_SUBSCRIBER_CLOSE_CODE, "Capture subscriber cannot keep up."),
            )
        )

    async def _end_session(
        self, client: dict[str, Any], code: str, message: str
    ) -> None:
        """Unregister a finished capture and notify/detach its subscribers.

        Idempotent: safe to call from both stream teardown and stop paths.
        """
        session_id = client.get("session_id")
        client["session_id"] = None
        client["session_config"] = None
        client["namespace"] = None
        client["session_end"] = None
        if session_id:
            self.sessions.pop(session_id, None)
        client.setdefault("pcapng_buffer", bytearray()).clear()
        client.setdefault("pcapng_header", bytearray()).clear()
        client["pcapng_endian"] = None
        client["pcapng_header_complete"] = False

        notification_targets = []
        for subscriber in list(client.get("subscribers", set())):
            sub_client = self.clients.get(subscriber)
            if sub_client and sub_client.get("subscribed_to") == session_id:
                queue = sub_client.get("subscription_queue")
                if queue is None:
                    notification_targets.append(subscriber)
                else:
                    try:
                        queue.put_nowait(
                            (
                                "event",
                                self._event_text(
                                    "status",
                                    code,
                                    {"message": message, "session_id": session_id},
                                ),
                            )
                        )
                        queue.put_nowait(("done", None))
                    except asyncio.QueueFull:
                        self._close_subscription_queue(sub_client)
            client["subscribers"].discard(subscriber)
        if notification_targets:
            await asyncio.gather(
                *(
                    asyncio.wait_for(
                        self.send_event(
                            subscriber,
                            "status",
                            code,
                            {"message": message, "session_id": session_id},
                        ),
                        timeout=_SUBSCRIBER_SEND_TIMEOUT_SEC,
                    )
                    for subscriber in notification_targets
                ),
                return_exceptions=True,
            )

    def _session_descriptor(
        self, session_id: str, owner_ws: WebSocket
    ) -> dict[str, Any]:
        """Describe a running capture and its requested configuration."""
        owner_client = self.clients.get(owner_ws, {})
        return {
            "session_id": session_id,
            "owner": owner_client.get("did"),
            "interfaces": sorted(owner_client.get("interfaces", set())),
            "namespace": owner_client.get("namespace"),
            "config": owner_client.get("session_config"),
        }

    async def subscribe(self, websocket: WebSocket, session_id: str | None) -> None:
        """Attach this socket as a read-only listener on a running capture.

        Any authenticated principal on the device may listen; only the owning
        socket can configure or stop the capture (control is not shareable).
        """
        client = self.clients.get(websocket)
        if client is None:
            return
        if not isinstance(session_id, str) or not session_id:
            await self.send_message_event(
                websocket,
                "error",
                "SESSION_NOT_FOUND",
                f"No running capture session: {session_id}",
            )
            return
        owner_ws = self.sessions.get(session_id)
        if owner_ws is None:
            await self.send_message_event(
                websocket,
                "error",
                "SESSION_NOT_FOUND",
                f"No running capture session: {session_id}",
            )
            return
        if client.get("session_id"):
            await self.send_message_event(
                websocket,
                "error",
                "SESSION_IS_OWN",
                "A capture owner cannot subscribe to another capture.",
            )
            return
        await self._detach_subscriber(websocket)
        owner_ws = self.sessions.get(session_id)
        if owner_ws is None:
            await self.send_message_event(
                websocket,
                "error",
                "SESSION_NOT_FOUND",
                f"No running capture session: {session_id}",
            )
            return
        owner_client = self.clients.get(owner_ws)
        if owner_client is None:
            await self.send_message_event(
                websocket,
                "error",
                "SESSION_NOT_FOUND",
                f"No running capture session: {session_id}",
            )
            return

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_BLOCKS
        )
        queue.put_nowait(
            (
                "event",
                self._event_text(
                    "status",
                    "SUBSCRIBED",
                    self._session_descriptor(session_id, owner_ws),
                ),
            )
        )
        header = bytes(owner_client.get("pcapng_header", b""))
        if header:
            queue.put_nowait(("bytes", header))
        client["subscribed_to"] = session_id
        client["subscription_queue"] = queue
        client["subscription_closing"] = False
        owner_client["subscribers"].add(websocket)
        client["subscription_task"] = asyncio.create_task(
            self._send_subscription(websocket, session_id, queue)
        )

    async def unsubscribe(self, websocket: WebSocket) -> None:
        """Detach a subscriber from its session."""
        session_id = (self.clients.get(websocket) or {}).get("subscribed_to")
        await self._detach_subscriber(websocket)
        await self.send_event(
            websocket, "status", "UNSUBSCRIBED", {"session_id": session_id}
        )

    async def send_session_list(self, websocket: WebSocket) -> None:
        """Send the list of running capture sessions."""
        sessions = [
            self._session_descriptor(session_id, owner_ws)
            for session_id, owner_ws in self.sessions.items()
        ]
        await self.send_event(websocket, "status", "SESSIONS", {"sessions": sessions})

    @staticmethod
    def _pcapng_blocks(client: dict[str, Any], chunk: bytes) -> list[bytes]:
        """Frame dumpcap's arbitrary stdout chunks into complete pcapng blocks."""
        buffer = client.setdefault("pcapng_buffer", bytearray())
        buffer.extend(chunk)
        blocks = []

        while len(buffer) >= 12:
            if client.get("pcapng_endian") is None:
                start = buffer.find(_PCAPNG_SECTION_HEADER)
                if start < 0:
                    del buffer[:-3]
                    break
                if start:
                    del buffer[:start]
                if len(buffer) < 12:
                    break

            if bytes(buffer[:4]) == _PCAPNG_SECTION_HEADER:
                byte_order_magic = bytes(buffer[8:12])
                if byte_order_magic == b"\x4d\x3c\x2b\x1a":
                    client["pcapng_endian"] = "little"
                elif byte_order_magic == b"\x1a\x2b\x3c\x4d":
                    client["pcapng_endian"] = "big"
                else:
                    del buffer[0]
                    client["pcapng_endian"] = None
                    continue

            endian = client["pcapng_endian"]
            total_length = int.from_bytes(buffer[4:8], endian)
            if total_length < 12 or total_length % 4:
                del buffer[0]
                client["pcapng_endian"] = None
                continue
            if len(buffer) < total_length:
                break
            if (
                int.from_bytes(buffer[total_length - 4 : total_length], endian)
                != total_length
            ):
                del buffer[0]
                client["pcapng_endian"] = None
                continue

            block = bytes(buffer[:total_length])
            del buffer[:total_length]
            block_type = int.from_bytes(block[:4], endian)
            if block[:4] == _PCAPNG_SECTION_HEADER:
                client["pcapng_header"] = bytearray()
                client["pcapng_header_complete"] = False
            if not client.get("pcapng_header_complete"):
                if block_type in _PCAPNG_PACKET_BLOCK_TYPES:
                    client["pcapng_header_complete"] = True
                else:
                    client["pcapng_header"].extend(block)
            blocks.append(block)

        return blocks

    def _queue_subscriber_block(self, client: dict[str, Any], block: bytes) -> None:
        session_id = client.get("session_id")
        for subscriber in list(client.get("subscribers", set())):
            sub_client = self.clients.get(subscriber)
            if not sub_client or sub_client.get("subscribed_to") != session_id:
                client["subscribers"].discard(subscriber)
                continue
            queue = sub_client.get("subscription_queue")
            if sub_client.get("subscription_closing"):
                client["subscribers"].discard(subscriber)
                continue
            if queue is None:
                self._clear_subscription(subscriber, session_id)
                continue
            try:
                queue.put_nowait(("bytes", block))
            except asyncio.QueueFull:
                client["subscribers"].discard(subscriber)
                self._close_subscription_queue(sub_client)

    async def _broadcast_chunk(
        self, owner_ws: WebSocket, client: dict[str, Any], chunk: bytes
    ) -> None:
        # The owner keeps dumpcap's original chunks. Subscribers receive complete
        # blocks so a replayed section header is followed at a valid boundary.
        await owner_ws.send_bytes(chunk)
        for block in self._pcapng_blocks(client, chunk):
            self._queue_subscriber_block(client, block)

    async def _stop_channel_tasks(self, client: dict[str, Any]) -> None:
        channel_tasks = list(client.get("channel_tasks", {}).values())
        client["channel_tasks"] = {}
        for channel_task in channel_tasks:
            channel_task.cancel()
        for channel_task in channel_tasks:
            try:
                await channel_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.debug("Channel hopping task shutdown failed: %s", exc)

    def configure(self, websocket: WebSocket, iface: str, config: Any) -> None:
        """Validate and store capture config for an interface."""
        if websocket in self.clients:
            iface = validate_capture_interface(iface)
            validated = CaptureInterfaceConfig.model_validate(config)
            self.clients[websocket]["configs"][iface] = validated.model_dump()

    async def disconnect(self, websocket: WebSocket) -> None:
        """Clean up a disconnecting client."""
        await self._detach_subscriber(websocket)
        try:
            await self.stop_streaming(websocket)
        except Exception as e:
            log.warning(f"disconnect() failed: {e!r}")
        self.clients.pop(websocket, None)

    async def send_event(
        self, websocket: WebSocket, event_type: str, code: str, data: dict[str, Any]
    ) -> None:
        """Send a JSON event to the websocket, ignoring errors."""
        try:
            await websocket.send_text(self._event_text(event_type, code, data))
        except RuntimeError:
            pass
        except Exception as e:
            log.debug(f"send_event() failed: {e!r}")

    @staticmethod
    def _event_text(event_type: str, code: str, data: dict[str, Any]) -> str:
        return json.dumps(
            {"type": "event", "event": event_type, "code": code, "data": data}
        )

    async def send_message_event(
        self, websocket: WebSocket, event_type: str, code: str, message: str
    ) -> None:
        """Send a message-only event to the websocket."""
        await self.send_event(websocket, event_type, code, {"message": message})

    async def send_supported_frequencies(self, websocket: WebSocket) -> None:
        """Send supported channel frequencies for capture adapters."""
        try:
            # Discover capture adapters across all namespaces via core's own
            # enumeration, then query each phy inside its namespace, so a
            # namespaced adapter is not invisible here.
            from wlanpi_core.adapters.interface import get_interface_info

            status = await asyncio.to_thread(network_config.status)
            adapters = [
                a for a in iter_adapters(status) if a["iface"].startswith("wlanpi")
            ]

            freqs_by_iface: dict[str, list[int]] = {}
            for adapter in adapters:
                iface = adapter["iface"]
                namespace = adapter["namespace"]
                try:
                    info = await asyncio.to_thread(get_interface_info, iface, namespace)
                    phy = (info or {}).get("phy")
                    if not phy:
                        freqs_by_iface[iface] = []
                        continue
                    chan_output = (
                        await run_command_async(
                            [
                                *self._ns_prefix(namespace),
                                IW_FILE,
                                "phy",
                                phy,
                                "channels",
                            ],
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

    @staticmethod
    def _ns_prefix(namespace: str | None) -> list[str]:
        """Command prefix to run in a network namespace. Empty for root.

        wlanpi-core runs as root, so `ip netns exec` needs no sudo. The whole
        phy moves into a namespace together, so all vifs on it share one ns.
        """
        if not namespace:
            return []
        return ["ip", "netns", "exec", validate_namespace_name(namespace)]

    async def _resolve_namespace(
        self, interfaces: list[str]
    ) -> tuple[str | None, str | None]:
        """Find the namespace the capture interfaces live in.

        Uses core's own adapter enumeration (network_config.status), never a
        bespoke iw call.

        Returns (namespace, error). namespace is None for root. error is a
        short reason string when the interfaces are missing or split across
        namespaces (dumpcap cannot span netns).
        """
        status = await asyncio.to_thread(network_config.status)
        adapters = iter_adapters(status)
        by_name: dict[str, list[dict[str, Any]]] = {}
        for a in adapters:
            by_name.setdefault(a["iface"], []).append(a)

        namespaces: set[str | None] = set()
        for iface in interfaces:
            records = by_name.get(iface)
            if not records:
                return None, f"interface not found on this device: {iface}"
            namespaces.update(r["namespace"] for r in records)
        if len(namespaces) > 1:
            return None, (
                "capture interfaces span multiple namespaces "
                f"({sorted(str(n) for n in namespaces)}); one capture cannot"
            )
        return (namespaces.pop() if namespaces else None), None

    async def start_streaming(
        self,
        websocket: WebSocket,
        interfaces: list[str],
        pcap_filter: str | None,
    ) -> None:
        """Start a capture session for the websocket."""
        client = self.clients.get(websocket)
        if not client:
            await self.send_message_event(
                websocket,
                "error",
                "CLIENT_NOT_FOUND",
                "WebSocket client not registered.",
            )
            return

        if client.get("subscribed_to"):
            await self.send_message_event(
                websocket,
                "error",
                "SUBSCRIBER_READ_ONLY",
                "Unsubscribe before starting a capture.",
            )
            return

        try:
            start = CaptureStart(
                interfaces=interfaces,
                pcap_filter=pcap_filter or "",
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

        if (client["task"] and not client["task"].done()) or (
            client["proc"] and client["proc"].returncode is None
        ):
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

        conflicts = self._claim_interfaces(websocket, interfaces)
        if conflicts:
            await self.send_message_event(
                websocket,
                "error",
                "INTERFACE_IN_USE",
                f"Capture interface already in use: {', '.join(conflicts)}",
            )
            return

        namespace, ns_error = await self._resolve_namespace(interfaces)
        if ns_error:
            self._release_interfaces(websocket)
            await self.send_message_event(
                websocket, "error", "INTERFACE_NOT_AVAILABLE", ns_error
            )
            return
        client["namespace"] = namespace
        client["pcapng_buffer"].clear()
        client["pcapng_header"].clear()
        client["pcapng_endian"] = None
        client["pcapng_header_complete"] = False
        client["session_end"] = None

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
                    error = await self._set_channel(iface, freq, width, namespace)
                    if error:
                        # Warn but continue: capture on whatever channel the
                        # radio is currently on rather than aborting. This is
                        # what keeps single-radio devices usable when the
                        # managed vif briefly holds the phy (see the busy retry
                        # in _set_channel). Do not turn this into a hard abort.
                        await self.send_message_event(
                            websocket,
                            "error",
                            "CHANNEL_SET_FAILED",
                            f"Could not set initial channel for {iface}: {error}",
                        )

        args = [*self._ns_prefix(namespace), DUMPCAP_FILE]
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
        except OSError as e:
            self._release_interfaces(websocket)
            log.warning(f"Failed to start capture process: {e!r}")
            await self.send_message_event(
                websocket, "error", "CAPTURE_START_FAILED", "Failed to start capture."
            )
            return

        async def stream() -> None:
            try:
                if proc.stdout is None:
                    await self.send_message_event(
                        websocket, "status", "CAPTURE_ENDED", "Capture ended."
                    )
                    return
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    await self._broadcast_chunk(websocket, client, chunk)
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
                await self._stop_channel_tasks(client)
                self._release_interfaces(websocket)
                code, message = client.get("session_end") or (
                    "CAPTURE_ENDED",
                    "Capture ended.",
                )
                client["session_end"] = None
                await self._end_session(client, code, message)
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

        session_id = f"cap_{secrets.token_hex(4)}"
        client["session_id"] = session_id
        # Snapshot the requested config so subscribers know what the owner
        # asked dumpcap and the channel hopper to capture.
        client["session_config"] = {
            "interfaces": {
                iface: client["configs"].get(iface, {}) for iface in interfaces
            },
            "pcap_filter": pcap_filter,
        }
        self.sessions[session_id] = websocket

        await self.send_event(
            websocket,
            "status",
            "CAPTURE_STARTED",
            {
                "message": f"Started capture on {', '.join(interfaces)}",
                "session_id": session_id,
                "interfaces": sorted(interfaces),
                "namespace": namespace,
                "config": client["session_config"],
            },
        )

    async def stop_streaming(self, websocket: WebSocket, notify: bool = True) -> None:
        """Stop and clean up a capture session."""
        client = self.clients.get(websocket)
        if not client:
            return

        if client.get("subscribed_to"):
            if notify:
                await self.send_message_event(
                    websocket,
                    "error",
                    "SUBSCRIBER_READ_ONLY",
                    "A subscriber cannot stop the owner's capture.",
                )
            return

        task = client.get("task")
        proc = client.get("proc")
        if client.get("session_id"):
            client["session_end"] = ("CAPTURE_STOPPED", "Capture stopped.")
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

        await self._stop_channel_tasks(client)
        self._release_interfaces(websocket)
        await self._end_session(client, "CAPTURE_STOPPED", "Capture stopped.")

        client["task"] = None
        client["proc"] = None

        if notify:
            try:
                await self.send_message_event(
                    websocket, "status", "CAPTURE_STOPPED", "Capture stopped."
                )
            except Exception:
                pass

    async def shutdown_all(self) -> None:
        """Stop every capture and discard all client state during app shutdown."""
        for websocket in list(self.clients):
            try:
                await self.stop_streaming(websocket, notify=False)
            except Exception as exc:
                log.warning("Capture shutdown failed for a client: %r", exc)
        subscription_tasks: list[asyncio.Task[Any]] = []
        for client in self.clients.values():
            task = client.get("subscription_task")
            if task is not None:
                subscription_tasks.append(task)
        for task in subscription_tasks:
            task.cancel()
        if subscription_tasks:
            await asyncio.gather(*subscription_tasks, return_exceptions=True)
        self.clients.clear()
        self.interface_owners.clear()
        self.sessions.clear()

    async def _hop_channels(
        self, websocket: WebSocket, iface: str, channels: list[Any], dwell_time_ms: int
    ) -> None:
        async def apply_channel(ch: dict[str, Any]) -> None:
            freq = ch.get("freq")
            width = ch.get("width")

            if freq and width:
                error = await self._set_channel(
                    iface, freq, width, self.clients.get(websocket, {}).get("namespace")
                )
                if not error:
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
                        f"{iface}: failed to set {freq} MHz / {width} MHz ({error})",
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

    async def _set_channel(
        self, iface: str, freq: int, width: int, namespace: str | None = None
    ) -> str | None:
        """Tune a capture interface to the requested channel.

        Returns None on success, else a short reason suitable for the
        CHANNEL_SET_FAILED event (e.g. iw's 'Device or resource busy (-16)'
        when a managed vif on the same phy blocks retuning, common on
        single-radio devices).
        """
        try:
            iface = validate_capture_interface(iface)
            freq = validate_capture_frequency(freq)
            width = validate_capture_width(width)
        except ValueError as exc:
            return str(exc)

        cmd = [
            *self._ns_prefix(namespace),
            IW_FILE,
            "dev",
            iface,
            "set",
            "freq",
            str(freq),
            str(width),
        ]

        if width >= 40:
            center_frequency = self._center_frequency(freq, width)
            if center_frequency < 0:
                return "no valid center frequency for this channel/width"
            cmd.append(str(center_frequency))

        # A shared phy is briefly locked while another vif scans (e.g.
        # wpa_supplicant's periodic scan on a disconnected managed vif), so
        # EBUSY here is often transient: retry once before reporting.
        detail = ""
        for attempt in range(2):
            try:
                result = await run_command_async(
                    cmd,
                    raise_on_fail=False,
                    timeout=_IW_TIMEOUT_SEC,
                )
            except (RunCommandError, OSError) as exc:
                return str(exc)
            if result.success:
                return None
            lines = (result.stderr or result.stdout or "").strip().splitlines()
            detail = lines[-1] if lines else f"iw exited {result.return_code}"
            if attempt == 0 and "busy" in detail.lower():
                await asyncio.sleep(0.3)
                continue
            break
        return detail

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
