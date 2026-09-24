"""Profiler beaconing status and data helpers."""

import json
import os
import shutil
import stat
from typing import Any

import psutil

import wlanpi_core.profiler.cli as cli
from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services.system_service import check_service_status

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


def profiler_active() -> bool:
    """Return True while any profiler run could still be writing its output.

    Covers the wlanpi-profiler systemd unit, a profiler Core spawned itself,
    and a profiler started some other way that reports `starting` or
    `running` in its status file (ignored when its pid is gone).
    """
    process = cli.profiler_process
    if process is not None and process.returncode is None:
        return True
    try:
        with open(cli.STATUS_FILE) as f:
            status = json.load(f)
    except (OSError, ValueError):
        status = {}
    if isinstance(status, dict) and status.get("state") in ("starting", "running"):
        pid = status.get("pid")
        if not isinstance(pid, int) or psutil.pid_exists(pid):
            return True
    return check_service_status("wlanpi-profiler")


def _tree_usage(path: str) -> tuple[int, int]:
    """Return (file count, byte count) under path, not following symlinks."""
    files = size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        # os.walk lists a symlink to a directory under dirnames.
        for name in dirnames + filenames:
            st = os.lstat(os.path.join(dirpath, name))
            if not stat.S_ISDIR(st.st_mode):
                files += 1
                size += st.st_size
    return files, size


def purge_data() -> dict[str, int]:
    """Delete everything inside the profiler clients and reports directories.

    The directories themselves stay, with their mode and ownership. Symlinks
    are removed, never followed. Raises ValidationError (409) while the
    profiler is active.
    """
    # ponytail: check-then-delete; a profiler started in between may lose a
    # file it is writing. Hold a start lock here if that ever matters.
    if profiler_active():
        raise ValidationError(
            "The profiler is running; stop it before purging its data.",
            status_code=409,
        )
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
            if entry.is_dir(follow_symlinks=False):
                count, used = _tree_usage(entry.path)
                shutil.rmtree(entry.path)
            else:
                count, used = 1, entry.stat(follow_symlinks=False).st_size
                os.unlink(entry.path)
            files += count
            size += used
    log.info("Purged %d profiler files (%d bytes)", files, size)
    return {"files": files, "bytes": size}
