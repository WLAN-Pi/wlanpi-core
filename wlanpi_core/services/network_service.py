import socket

import httpx
from httpx import Response

from wlanpi_core.models.validation_error import ValidationError

from .helpers import get_local_ip_async, run_cli_async


async def get_neighbor_results():
    """
    Run `lldpcli show neighbors -f json` and return results
    """

    return await run_cli_async("/usr/sbin/lldpcli show neighbors -f json")


async def get_public_ipv4():
    url = "https://ifconfig.co/json"

    async with httpx.AsyncClient() as client:
        resp: Response = await client.get(url)
        if resp.status_code != 200:
            raise ValidationError(content=resp.text, status_code=resp.status_code)

    # TODO: HANDLE IF RESP DOESN'T MATCH SCHEMA I.E. INTERNAL SERVER ERROR 

    return resp.json()


async def get_local_ip():
    ip = await get_local_ip_async()
    return {"ip": ip}


async def get_internet(host, port, timeout):
    """
    Host: 8.8.8.8 (google-public-dns-a.google.com)
    OpenPort: 53/tcp
    Service: domain (DNS/TCP)
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as ex:
        return False
