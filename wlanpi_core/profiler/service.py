"""Profiler beaconing status and data helpers."""

import asyncio
import json
import os
import shutil
import stat
from datetime import UTC, datetime
from typing import Any

import psutil

import wlanpi_core.profiler.cli as cli
from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services.system_service import get_service_active_state

INFO_FILE = "/run/wlanpi-profiler.info.json"
# The profiler writes its output here; purge empties these subdirectories.
DATA_ROOT = "/var/www/html/profiler"
PURGE_DIRS = ("clients", "reports")

log = get_logger(__name__)


def get_status() -> dict[str, Any]:
    """Return the profiler status and beaconing SSID."""
    running = profiler_beaconing()
    ssid = profiler_beaconing_ssid()

    return {
        "running": running,
        "ssid": ssid,
        "passphrase": _profiler_passphrase() if running else None,
    }


def _profiler_info() -> dict[str, Any]:
    """Read the profiler info file, or an empty mapping when unavailable."""
    try:
        with open(INFO_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _profiler_passphrase() -> str | None:
    """Return the passphrase the profiler is actually using, if any."""
    value = _profiler_info().get("passphrase")
    return value if isinstance(value, str) and value else None


def profiler_beaconing() -> bool:
    """Check whether the Profiler is beaconing.

    Probes the presence of /var/run/wlanpi-profiler.ssid.
    """
    ssid_file = "/var/run/wlanpi-profiler.ssid"
    if os.path.exists(ssid_file):
        return True
    else:
        return False


def profiler_beaconing_ssid() -> str | None:
    """Return the SSID currently in use by the Profiler."""
    ssid_file = "/var/run/wlanpi-profiler.ssid"
    if os.path.exists(ssid_file):
        with open(ssid_file) as f:
            return f.read()
    return None


def _status_pid_alive() -> bool:
    """Return True if the status file says starting/running for a live pid.

    A file without a valid pid is not trusted: a crashed profiler leaves one
    behind, and the pre-status window is covered by Core's process handle and
    the systemd unit state.
    """
    try:
        with open(cli.STATUS_FILE) as f:
            status = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(status, dict) or status.get("state") not in (
        "starting",
        "running",
    ):
        return False
    pid = status.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    return bool(psutil.pid_exists(pid))


def profiler_active() -> bool:
    """Return True while any profiler run could still be writing its output.

    Covers a profiler Core spawned itself, one whose status file reports
    `starting` or `running` with a live pid, and the wlanpi-profiler systemd
    unit in any state but inactive or failed (so activating, deactivating and
    reloading count as busy).
    """
    process = cli.profiler_process
    if process is not None and process.returncode is None:
        return True
    if _status_pid_alive():
        return True
    return get_service_active_state(cli.PROFILER_UNIT) not in ("inactive", "failed")


def _ignore_missing(func: Any, path: str, exc: BaseException) -> None:
    """Let rmtree skip entries that disappeared underneath it."""
    if not isinstance(exc, FileNotFoundError):
        raise exc


def _tree_usage(path: str) -> tuple[int, int]:
    """Return (file count, byte count) under path, not following symlinks."""
    files = size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        # os.walk lists a symlink to a directory under dirnames.
        for name in dirnames + filenames:
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(st.st_mode):
                files += 1
                size += st.st_size
    return files, size


def _delete_contents() -> dict[str, int]:
    """Empty the purge directories; entries removed concurrently are skipped."""
    files = size = 0
    for name in PURGE_DIRS:
        path = os.path.join(DATA_ROOT, name)
        if os.path.islink(path):
            log.warning("Not purging %s: it is a symlink", path)
            continue
        try:
            entries = list(os.scandir(path))
        except FileNotFoundError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    count, used = _tree_usage(entry.path)
                    shutil.rmtree(entry.path, onexc=_ignore_missing)
                else:
                    count, used = 1, entry.stat(follow_symlinks=False).st_size
                    os.unlink(entry.path)
            except FileNotFoundError:
                continue
            files += count
            size += used
    log.info("Purged %d profiler files (%d bytes)", files, size)
    return {"files": files, "bytes": size}


MEDIA_TYPES = {
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".pcap": "application/vnd.tcpdump.pcap",
    ".csv": "text/csv; charset=utf-8",
}
OTHER_MEDIA_TYPE = "application/octet-stream"
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY


def _open_below_root(parts: list[str], flags: int) -> int:
    """Open DATA_ROOT/parts one component at a time, never following a symlink.

    DATA_ROOT itself may be a symlink; nothing below it may. Opening each
    directory relative to its parent's descriptor leaves no window to swap a
    component for a symlink between a check and the open.
    """
    fd = os.open(DATA_ROOT, _DIR_FLAGS)
    try:
        for name in parts[:-1]:
            child = os.open(name, _DIR_FLAGS | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return os.open(parts[-1], flags | os.O_NOFOLLOW, dir_fd=fd)
    finally:
        os.close(fd)


def _utf8(name: str) -> bool:
    """Return True if name is valid UTF-8 and so can go into a JSON response."""
    try:
        name.encode()
    except UnicodeEncodeError:
        return False
    return True


def _entries(parts: list[str]) -> list[tuple[str, os.stat_result]]:
    """Return (name, lstat) for each entry of directory DATA_ROOT/parts, by name.

    None if it is missing, not a directory, or reached through a symlink.
    Skips names that are not valid UTF-8 and entries removed while listing.
    """
    try:
        fd = _open_below_root(parts, _DIR_FLAGS)
    except OSError:
        return []
    entries = []
    try:
        # DirEntry.stat() on an fd-based scandir uses fd, so stat before closing it.
        with os.scandir(fd) as it:
            for entry in it:
                if not _utf8(entry.name):
                    continue
                try:
                    entries.append((entry.name, entry.stat(follow_symlinks=False)))
                except FileNotFoundError:
                    continue
    finally:
        os.close(fd)
    return sorted(entries)


def _regular_files(parts: list[str]) -> list[dict[str, Any]]:
    """Describe the regular files directly in DATA_ROOT/parts, skipping symlinks."""
    return [
        {
            "path": "/".join([*parts, name]),
            "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, UTC),
        }
        for name, st in _entries(parts)
        if stat.S_ISREG(st.st_mode)
    ]


def list_files(mac: str | None = None) -> dict[str, Any]:
    """List the client profile files and session reports.

    mac, as dash-separated lowercase hex like the profiler's directory names,
    limits clients to that one. Symlinks are skipped, never followed.
    """
    clients = []
    # A non-directory or symlinked entry yields no files, so it is not listed.
    for name, _ in _entries(["clients"]):
        if mac is not None and name != mac:
            continue
        files = _regular_files(["clients", name])
        if files:
            clients.append({"mac": name.replace("-", ":"), "files": files})
    return {"clients": clients, "reports": _regular_files(["reports"])}


def read_file(path: str) -> tuple[bytes, str]:
    """Return the bytes and media type of one profiler file.

    path is relative to DATA_ROOT and must be `clients/<dir>/<file>` or
    `reports/<file>`. Raises ValidationError (404) for anything else, a
    symlink anywhere below DATA_ROOT, or a file that is not regular.
    """
    not_found = ValidationError("Profiler file not found", status_code=404)
    parts = path.split("/")
    depth = {"clients": 3, "reports": 2}.get(parts[0])
    if len(parts) != depth or any(p in ("", ".", "..") or "\0" in p for p in parts):
        raise not_found
    # O_NONBLOCK keeps a FIFO from blocking the open; fstat then rejects it.
    try:
        fd = _open_below_root(parts, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
    except OSError:
        raise not_found from None
    # shortcut: reads the whole file; profiler files are a few KB, and a day's
    # CSV report tens of KB. Stream it if they ever grow to many MB.
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise not_found
        content = f.read()
    media_type = MEDIA_TYPES.get(os.path.splitext(path)[1].lower(), OTHER_MEDIA_TYPE)
    return content, media_type


async def purge_data() -> dict[str, int]:
    """Delete everything inside the profiler clients and reports directories.

    The directories themselves stay, with their mode and ownership. Symlinks
    are removed, never followed. Raises ValidationError (409) while the
    profiler is active.

    Holds the lock Core takes to start or stop the profiler, whether it
    spawns it directly or starts the systemd unit, so a purge never overlaps
    another purge or a start through Core. Activity is checked under that
    lock right before deleting.
    """
    # ponytail: only starts from outside Core (direct systemctl, FPMS) take no
    # lock, so they can still begin between the check and the delete and lose
    # a file being written. Upgrade path: a lock the profiler itself honours.
    async with cli._profiler_lock:
        if await asyncio.to_thread(profiler_active):
            raise ValidationError(
                "The profiler is running; stop it before purging its data.",
                status_code=409,
            )
        return await asyncio.to_thread(_delete_contents)
