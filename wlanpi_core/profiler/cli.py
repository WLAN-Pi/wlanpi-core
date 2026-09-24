"""Start and stop the profiler subprocess."""

import asyncio
import json
import os
import time
from asyncio.subprocess import Process
from typing import Any

import wlanpi_core.profiler.models as models
from wlanpi_core.core.logging import get_logger
from wlanpi_core.utils.general import terminate_process_async

_PROFILER_STOP_GRACE_SEC = 10.0
# How long start waits for the profiler to report running or to exit.
# ponytail: kept under the MCP client's 30 s HTTP timeout; a slower start
# (No IR wait on a self-managed radio) returns reason "starting" instead.
_PROFILER_START_WAIT_SEC = 25.0
_PROFILER_START_POLL_SEC = 0.5
STATUS_FILE = "/run/wlanpi-profiler.status.json"
LAST_SESSION_FILE = "/var/lib/wlanpi-profiler/last-session.json"

log = get_logger(__name__)
profiler_process: Process | None = None
# Serialises start, stop and service.purge_data.
_profiler_lock = asyncio.Lock()


def _stamp(path: str) -> tuple[int, int] | None:
    """Return (inode, mtime_ns) for path, or None when it does not exist."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns)


def _read_if_changed(path: str, before: tuple[int, int] | None) -> dict[str, Any]:
    """Return the JSON object in path if it was rewritten since before.

    The profiler replaces these files atomically, so a new write shows up as a
    new inode or mtime. Comparing identities avoids trusting wall-clock order,
    which file mtime granularity makes unreliable.
    """
    if _stamp(path) in (None, before):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def _await_start(
    process: Process, session_before: tuple[int, int] | None
) -> dict[str, Any]:
    """Wait until the profiler reports running, exits, or the wait runs out.

    The profiler writes STATUS_FILE (state starting, running or failed, plus
    its pid) and, on exit, LAST_SESSION_FILE with the reason. A running state
    counts only when its pid is this child's. A last session counts only if
    it differs from session_before, taken before the spawn; a failed run
    leaves its files behind.
    """
    deadline = time.monotonic() + _PROFILER_START_WAIT_SEC
    while True:
        if process.returncode is not None:
            exit_info = _read_if_changed(LAST_SESSION_FILE, session_before).get("exit")
            if not isinstance(exit_info, dict):
                exit_info = {}
            return {
                "success": False,
                "reason": exit_info.get("reason") or "exited",
                "message": exit_info.get("message")
                or f"profiler exited with code {process.returncode} during startup",
            }
        status = _read_if_changed(STATUS_FILE, None)
        if status.get("state") == "running" and status.get("pid") == process.pid:
            return {"success": True}
        if time.monotonic() >= deadline:
            return {
                "success": True,
                "reason": "starting",
                "message": "profiler is still starting; poll GET /profiler/status",
            }
        try:
            await asyncio.wait_for(process.wait(), timeout=_PROFILER_START_POLL_SEC)
        except TimeoutError:
            pass


async def start_profiler(args: models.Start) -> dict[str, Any]:
    """Start the profiler and wait until it is running or has failed.

    Returns {"success": bool} plus "reason" and "message" when it did not
    start (for example "country_code_detection" or "interface_validation")
    or is still starting after the wait ("starting").
    """
    global profiler_process

    cmd = ["profiler"]
    value_options = {
        "-c": args.channel,
        "-f": args.frequency,
        "-i": args.interface,
        "-s": args.ssid,
    }
    for flag, value in value_options.items():
        if value:
            cmd += [flag, str(value)]

    bool_flags = [
        ("--debug", args.debug),
        ("--noprep", args.noprep),
        ("--noAP", args.noAP),
        ("--no11r", args.no11r),
        ("--no11ax", args.no11ax),
        ("--no11be", args.no11be),
        ("--noprofilertlv", args.noprofilertlv),
        ("--wpa3_personal_transition", args.wpa3_personal_transition),
        ("--wpa3_personal", args.wpa3_personal),
        ("--oui_update", args.oui_update),
        ("--no_bpf_filters", args.no_bpf_filters),
    ]
    cmd += [flag for flag, enabled in bool_flags if enabled]

    async with _profiler_lock:
        if profiler_process and profiler_process.returncode is None:
            return {
                "success": False,
                "reason": "already_running",
                "message": "the profiler is already running; stop it first",
            }

        if profiler_process:
            await profiler_process.wait()
            profiler_process = None

        session_before = _stamp(LAST_SESSION_FILE)
        try:
            # Output is inherited so the profiler's log lands in Core's journal.
            process = await asyncio.create_subprocess_exec(
                *cmd,
                start_new_session=True,
            )
        except OSError as error:
            log.error("Error starting profiler: %s", error)
            return {"success": False, "reason": "spawn_failed", "message": str(error)}
        profiler_process = process

    # Outside the lock, so a stop during startup is not blocked by this wait.
    result = await _await_start(process, session_before)
    if not result["success"]:
        log.error("Profiler did not start: %s: %s", result["reason"], result["message"])
    return result


async def stop_profiler() -> Any:
    """Stop the running profiler process."""
    global profiler_process

    async with _profiler_lock:
        if not profiler_process:
            return False

        process = profiler_process
        if process.returncode is not None:
            await process.wait()
            profiler_process = None
            return False

        # The profiler needs ~2 s after SIGTERM to stop hostapd, delete its
        # monitor vif and restore the primary; a SIGKILL before that leaves
        # the radio staged and breaks later captures on it.
        await terminate_process_async(process, grace=_PROFILER_STOP_GRACE_SEC)
        profiler_process = None
        return True
