"""
shared resources between services
"""

import asyncio
import os
import socket
from typing import Iterable, List, Tuple

from wlanpi_core.models.runcommand_error import RunCommandError


def get_phy80211_interfaces() -> List:
    interfaces = []
    path = "/sys/class/net"
    for net, ifaces, files in os.walk(path):
        for iface in ifaces:
            for dirpath, dirnames, filenames in os.walk(os.path.join(path, iface)):
                if "phy80211" in dirnames:
                    interfaces.append(iface)
    return interfaces


async def get_local_ipv4_async() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # does not have to be reachable
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


async def get_local_ipv6_async() -> str:
    s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    try:
        # does not have to be reachable
        s.connect(("fec0::aaaa", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "::1"
    finally:
        s.close()
    return ip


async def run_cli_async(cmd: str, want_stderr: bool = False) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode == 0:
        if stdout:
            return stdout.decode()
        if stderr and want_stderr:
            return stderr.decode()

    if stderr:
        raise RunCommandError(
            status_code=424, error_msg=f"'{cmd}' gave stderr response"
        )


def flag_last_object(_iterable: Iterable) -> Tuple[any, bool]:
    """Treat the last object in an iterable differently"""
    _iterable = iter(_iterable)  # ensure _iterable is an iterator
    a = next(_iterable)
    for b in _iterable:
        yield a, False
        a = b
    yield a, True
