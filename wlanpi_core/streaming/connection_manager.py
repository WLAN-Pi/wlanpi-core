import asyncio
import json
import re
import secrets
from typing import Any, Dict, Optional, Tuple

from fastapi import WebSocket

from wlanpi_core.constants import DUMPCAP_FILE, IW_FILE
from wlanpi_core.core.logging import get_logger
from wlanpi_core.utils import network_config
from wlanpi_core.utils.general import run_command_async, terminate_process_async
from wlanpi_core.utils.validation import validate_namespace_name
from wlanpi_core.wlan.scan import iter_adapters
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
        self.interface_owners: Dict[str, WebSocket] = {}
        # Running captures by session id -> owning WebSocket. Sessions exist
        # so other authenticated principals can subscribe read-only (#141).
        self.sessions: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket) -> None:
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
        }
        await websocket.accept()

    def authenticate(self, websocket: WebSocket, did: str) -> None:
        """Record the verified principal for this socket. Commands are only
        dispatched after this is set (first-message auth in the endpoint)."""
        client = self.clients.get(websocket)
        if client is not None:
            client["did"] = did

    def is_authenticated(self, websocket: WebSocket) -> bool:
        client = self.clients.get(websocket)
        return bool(client and client.get("did"))

    def _claim_interfaces(
        self, websocket: WebSocket, interfaces: list[str]
    ) -> list[str]:
        """Atomically claim capture interfaces for one WebSocket client."""
        conflicts = sorted(
            iface
            for iface in interfaces
            if (owner := self.interface_owners.get(iface)) is not None
            and owner is not websocket
        )
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

    def _detach_subscriber(self, websocket: WebSocket) -> None:
        client = self.clients.get(websocket)
        if not client:
            return
        session_id = client.get("subscribed_to")
        client["subscribed_to"] = None
        if not session_id:
            return
        owner_ws = self.sessions.get(session_id)
        if owner_ws is not None:
            owner_client = self.clients.get(owner_ws)
            if owner_client:
                owner_client["subscribers"].discard(websocket)

    async def _end_session(self, client: Dict[str, Any], code: str, message: str) -> None:
        """Unregister a finished capture and notify/detach its subscribers.
        Idempotent: safe to call from both stream teardown and stop paths."""
        session_id = client.get("session_id")
        client["session_id"] = None
        client["session_config"] = None
        client["namespace"] = None
        if session_id:
            self.sessions.pop(session_id, None)
        for subscriber in list(client.get("subscribers", set())):
            sub_client = self.clients.get(subscriber)
            if sub_client:
                sub_client["subscribed_to"] = None
            client["subscribers"].discard(subscriber)
            await self.send_message_event(subscriber, "status", code, message)

    def _session_descriptor(self, session_id: str, owner_ws: WebSocket) -> dict:
        """Public description of a running capture: who owns it and the exact
        config it is running (channels/width/dwell per interface + filter), so
        a subscriber is never blind to what it is receiving."""
        owner_client = self.clients.get(owner_ws, {})
        return {
            "session_id": session_id,
            "owner": owner_client.get("did"),
            "interfaces": sorted(owner_client.get("interfaces", set())),
            "config": owner_client.get("session_config"),
        }

    async def subscribe(self, websocket: WebSocket, session_id: Optional[str]) -> None:
        """Attach this socket as a read-only listener on a running capture.

        Any authenticated principal on the device may listen; only the owning
        socket can configure or stop the capture (control is not shareable).
        """
        client = self.clients.get(websocket)
        if client is None:
            return
        owner_ws = self.sessions.get(session_id) if session_id else None
        if owner_ws is None:
            await self.send_message_event(
                websocket, "error", "SESSION_NOT_FOUND",
                f"No running capture session: {session_id}",
            )
            return
        if owner_ws is websocket:
            await self.send_message_event(
                websocket, "error", "SESSION_IS_OWN",
                "This socket owns that capture; it already receives its stream.",
            )
            return
        self._detach_subscriber(websocket)
        owner_client = self.clients[owner_ws]
        owner_client["subscribers"].add(websocket)
        client["subscribed_to"] = session_id
        await self.send_event(
            websocket, "status", "SUBSCRIBED",
            self._session_descriptor(session_id, owner_ws),
        )

    async def unsubscribe(self, websocket: WebSocket) -> None:
        session_id = (self.clients.get(websocket) or {}).get("subscribed_to")
        self._detach_subscriber(websocket)
        await self.send_event(
            websocket, "status", "UNSUBSCRIBED", {"session_id": session_id}
        )

    async def send_session_list(self, websocket: WebSocket) -> None:
        sessions = [
            self._session_descriptor(session_id, owner_ws)
            for session_id, owner_ws in self.sessions.items()
        ]
        await self.send_event(websocket, "status", "SESSIONS", {"sessions": sessions})

    async def _broadcast_chunk(
        self, owner_ws: WebSocket, client: Dict[str, Any], chunk: bytes
    ) -> None:
        # Owner send failures propagate and end the capture (as before).
        # A failing subscriber is dropped without disturbing the capture.
        await owner_ws.send_bytes(chunk)
        for subscriber in list(client.get("subscribers", set())):
            try:
                await subscriber.send_bytes(chunk)
            except Exception:
                self._detach_subscriber(subscriber)

    async def _stop_channel_tasks(self, client: Dict[str, Any]) -> None:
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

    def configure(self, websocket: WebSocket, iface: str, config: dict) -> None:
        if websocket in self.clients:
            iface = validate_capture_interface(iface)
            validated = CaptureInterfaceConfig.model_validate(config)
            self.clients[websocket]["configs"][iface] = validated.model_dump()

    async def disconnect(self, websocket: WebSocket) -> None:
        self._detach_subscriber(websocket)
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
            # Discover capture adapters across all namespaces via core's own
            # enumeration, then query each phy inside its namespace, so a
            # namespaced adapter is not invisible here.
            from wlanpi_core.adapters.interface import get_interface_info

            status = await asyncio.to_thread(network_config.status)
            adapters = [
                a for a in iter_adapters(status) if a["iface"].startswith("wlanpi")
            ]

            freqs_by_iface = {}
            for adapter in adapters:
                iface = adapter["iface"]
                namespace = adapter["namespace"]
                try:
                    info = await asyncio.to_thread(
                        get_interface_info, iface, namespace
                    )
                    phy = (info or {}).get("phy")
                    if not phy:
                        freqs_by_iface[iface] = []
                        continue
                    chan_output = (
                        await run_command_async(
                            self._ns_prefix(namespace)
                            + [IW_FILE, "phy", phy, "channels"],
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
    def _ns_prefix(namespace: Optional[str]) -> list:
        """Command prefix to run in a network namespace. Empty for root.

        wlanpi-core runs as root, so `ip netns exec` needs no sudo. The whole
        phy moves into a namespace together, so all vifs on it share one ns.
        """
        if not namespace:
            return []
        return ["ip", "netns", "exec", validate_namespace_name(namespace)]

    async def _resolve_namespace(
        self, interfaces: list[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Find the namespace the capture interfaces live in, via core's own
        adapter enumeration (network_config.status) - never a bespoke iw call.

        Returns (namespace, error). namespace is None for root. error is a
        short reason string when the interfaces are missing or split across
        namespaces (dumpcap cannot span netns).
        """
        status = await asyncio.to_thread(network_config.status)
        adapters = iter_adapters(status)
        by_name: Dict[str, list] = {}
        for a in adapters:
            by_name.setdefault(a["iface"], []).append(a)

        namespaces = set()
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
                        await self.send_message_event(
                            websocket,
                            "error",
                            "CHANNEL_SET_FAILED",
                            f"Could not set initial channel for {iface}: {error}",
                        )

        args = self._ns_prefix(namespace) + [DUMPCAP_FILE]
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
            self._release_interfaces(websocket)
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
                await self._end_session(client, "CAPTURE_ENDED", "Capture ended.")
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
        # Snapshot the exact running config so list_sessions / SUBSCRIBED can
        # report it to subscribers (who otherwise only see raw frames).
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
                "config": client["session_config"],
            },
        )

    async def stop_streaming(self, websocket: WebSocket, notify: bool = True) -> None:
        client = self.clients.get(websocket)
        if not client:
            return

        task = client.get("task")
        proc = client.get("proc")
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
        self.clients.clear()
        self.interface_owners.clear()

    async def _hop_channels(
        self, websocket: WebSocket, iface: str, channels: list, dwell_time_ms: int
    ) -> None:
        async def apply_channel(ch: dict) -> None:
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
        self, iface: str, freq: int, width: int, namespace: Optional[str] = None
    ) -> Optional[str]:
        """Tune a capture interface. Returns None on success, else a short
        reason suitable for the CHANNEL_SET_FAILED event (e.g. iw's
        'Device or resource busy (-16)' when a managed vif on the same phy
        blocks retuning - common on single-radio devices)."""
        try:
            iface = validate_capture_interface(iface)
            freq = validate_capture_frequency(freq)
            width = validate_capture_width(width)
        except ValueError as exc:
            return str(exc)

        cmd = self._ns_prefix(namespace) + [
            IW_FILE, "dev", iface, "set", "freq", str(freq), str(width)
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
            except Exception as exc:
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
