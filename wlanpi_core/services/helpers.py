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

__20MHZ_FREQUENCY_CHANNEL_MAP = {
    2412: 1,
    2417: 2,
    2422: 3,
    2427: 4,
    2432: 5,
    2437: 6,
    2442: 7,
    2447: 8,
    2452: 9,
    2457: 10,
    2462: 11,
    2467: 12,
    2472: 13,
    2484: 14,
    5160: 32,
    5170: 34,
    5180: 36,
    5190: 38,
    5200: 40,
    5210: 42,
    5220: 44,
    5230: 46,
    5240: 48,
    5250: 50,
    5260: 52,
    5270: 54,
    5280: 56,
    5290: 58,
    5300: 60,
    5310: 62,
    5320: 64,
    5340: 68,
    5480: 96,
    5500: 100,
    5510: 102,
    5520: 104,
    5530: 106,
    5540: 108,
    5550: 110,
    5560: 112,
    5570: 114,
    5580: 116,
    5590: 118,
    5600: 120,
    5610: 122,
    5620: 124,
    5630: 126,
    5640: 128,
    5660: 132,
    5670: 134,
    5680: 136,
    5700: 140,
    5710: 142,
    5720: 144,
    5745: 149,
    5755: 151,
    5765: 153,
    5775: 155,
    5785: 157,
    5795: 159,
    5805: 161,
    5825: 165,
    5845: 169,
    5865: 173,
    5955: 1,
    5975: 5,
    5995: 9,
    6015: 13,
    6035: 17,
    6055: 21,
    6075: 25,
    6095: 29,
    6115: 33,
    6135: 37,
    6155: 41,
    6175: 45,
    6195: 49,
    6215: 53,
    6235: 57,
    6255: 61,
    6275: 65,
    6295: 69,
    6315: 73,
    6335: 77,
    6355: 81,
    6375: 85,
    6395: 89,
    6415: 93,
    6435: 97,
    6455: 101,
    6475: 105,
    6495: 109,
    6515: 113,
    6535: 117,
    6555: 121,
    6575: 125,
    6595: 129,
    6615: 133,
    6635: 137,
    6655: 141,
    6675: 145,
    6695: 149,
    6715: 153,
    6735: 157,
    6755: 161,
    6775: 165,
    6795: 169,
    6815: 173,
    6835: 177,
    6855: 181,
    6875: 185,
    6895: 189,
    6915: 193,
    6935: 197,
    6955: 201,
    6975: 205,
    6995: 209,
    7015: 213,
    7035: 217,
    7055: 221,
    7075: 225,
    7095: 229,
    7115: 233,
}