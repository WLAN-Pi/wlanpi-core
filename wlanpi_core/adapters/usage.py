"""Signs that another tool is using a wireless netdev.

Core does not take a radio that something else controls. A netdev is in use
when another tool set a mode Core never sets (AP, mesh, ...), when a
wpa_supplicant or hostapd that Core did not start is bound to it, or when
another netdev on the same radio is up (a monitor interface pins the
channel, e.g. wlanpi-profiler's `<iface>profiler` or kismet's).
"""

import logging
import os
import re
from pathlib import Path

from wlanpi_core.constants import NETNS_RUN_DIR, RUN_DIR
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.namespace_execution import ns_exec

log = logging.getLogger(__name__)

# Modes Core sets itself; anything else was set by another tool.
CORE_MODES = {"managed", "monitor"}

PROC = Path("/proc")
_FLAGS_RE = re.compile(r"^\d+:\s+([^:@\s]+)[^<]*<([^>]*)>")
_HOSTAPD_IFACE_RE = re.compile(r"^interface=(\S+)", re.MULTILINE)


def up_links(namespace: str | None) -> set[str]:
    """Return the links in `namespace` (None = root) that are administratively up."""
    try:
        result = ns_exec(
            ["ip", "-o", "link", "show"], namespace=namespace, no_output=True
        )
    except (RunCommandError, ValueError) as e:
        log.warning(f"Could not list links in {namespace or 'root'}: {e}")
        return set()
    up = set()
    for line in result.stdout.splitlines():
        match = _FLAGS_RE.match(line)
        if match and "UP" in match.group(2).split(","):
            up.add(match.group(1))
    return up


def _netns_inode(namespace: str | None) -> int | None:
    path = (
        PROC / "1" / "ns" / "net"
        if namespace is None
        else Path(NETNS_RUN_DIR) / namespace
    )
    try:
        return os.stat(path).st_ino
    except OSError:
        return None


def _cmdline(pid: str) -> list[str]:
    try:
        raw = (PROC / pid / "cmdline").read_bytes()
    except OSError:
        return []
    return [arg.decode(errors="replace") for arg in raw.split(b"\0") if arg]


def _option_values(argv: list[str], option: str) -> list[str]:
    """Values of `option` in argv, as `-i wlan0` or `-iwlan0`."""
    values = []
    for index, arg in enumerate(argv):
        if arg == option and index + 1 < len(argv):
            values.append(argv[index + 1])
        elif arg.startswith(option) and len(arg) > len(option):
            values.append(arg[len(option) :])
    return values


def _hostapd_ifaces(pid: str, argv: list[str]) -> list[str]:
    ifaces = _option_values(argv, "-i")
    for arg in argv[1:]:
        if arg.startswith("-") or not arg.endswith(".conf"):
            continue
        # Read through the process's root: hostapd may run with PrivateTmp.
        try:
            text = (PROC / pid / "root" / arg.lstrip("/")).read_text(errors="replace")
        except OSError:
            continue
        ifaces.extend(_HOSTAPD_IFACE_RE.findall(text))
    return ifaces


def _is_core_supplicant(argv: list[str]) -> bool:
    core_dir = str(Path(RUN_DIR) / "wpa") + os.sep
    return any(path.startswith(core_dir) for path in _option_values(argv, "-P"))


def foreign_users(iface: str, namespace: str | None) -> list[str]:
    """Return wpa_supplicant/hostapd processes Core did not start that use `iface`.

    Only processes in the same network namespace count, so a same-named
    interface elsewhere is not mistaken for this one.
    """
    want = _netns_inode(namespace)
    if want is None:
        return []
    users = []
    for proc in PROC.iterdir():
        if not proc.name.isdigit():
            continue
        argv = _cmdline(proc.name)
        prog = os.path.basename(argv[0]) if argv else ""
        if prog not in {"wpa_supplicant", "hostapd"}:
            continue
        try:
            if os.stat(proc / "ns" / "net").st_ino != want:
                continue
        except OSError:
            continue
        if prog == "wpa_supplicant":
            if iface in _option_values(argv, "-i") and not _is_core_supplicant(argv):
                users.append(f"wpa_supplicant (pid {proc.name})")
        elif iface in _hostapd_ifaces(proc.name, argv):
            users.append(f"hostapd (pid {proc.name})")
    return users
