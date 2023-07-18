import socket

import httpx
from httpx import Response

from wlanpi_core.models.validation_error import ValidationError

from .helpers import get_local_ipv4_async, get_local_ipv6_async, run_cli_async


async def get_neighbor_results():
    """
    Run `lldpcli show neighbors -f json` and return results
    """

    return await run_cli_async("/usr/sbin/lldpcli show neighbors -f json")


async def get_public_ipv4():
    """
    TODO: If host has IPv6 reachability, resp contains IPv6. Force IPv4.

    IPv4 or IPv6 still can be forced by passing the appropiate flag to your client, e.g curl -4 or curl -6.
    """
    url = "https://ifconfig.co/json"

    async with httpx.AsyncClient() as client:
        resp: Response = await client.get(url)
        if resp.status_code != 200:
            raise ValidationError(content=resp.text, status_code=resp.status_code)

    # TODO: HANDLE IF RESP DOESN'T MATCH SCHEMA I.E. INTERNAL SERVER ERROR

    return resp.json()


async def get_public_ipv6():
    """
    TODO: If host only has IPv4 reachability, resp contains IPv4. Force IPv6.

    IPv4 or IPv6 still can be forced by passing the appropiate flag to your client, e.g curl -4 or curl -6.
    """
    url = "https://ifconfig.co/json"

    async with httpx.AsyncClient() as client:
        resp: Response = await client.get(url)
        if resp.status_code != 200:
            raise ValidationError(content=resp.text, status_code=resp.status_code)

    # TODO: HANDLE IF RESP DOESN'T MATCH SCHEMA I.E. INTERNAL SERVER ERROR

    return resp.json()


async def get_local_ipv4():
    ip = await get_local_ipv4_async()
    return {"ipv4": ip}


async def get_local_ipv6():
    ip = await get_local_ipv6_async()
    return {"ipv6": ip}


async def get_ipv4_internet_reachability(host, port, timeout):
    """
    Host: 8.8.8.8 (google-public-dns-a.google.com)
    OpenPort: 53/tcp
    Service: domain (DNS/TCP)
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        socket.close()
        return True
    except socket.error as ex:
        socket.close()
        return False


async def get_ipv6_internet_reachability(host, port, timeout):
    """
    Host: 2001:4860:4860::8888 (dns.google)
    OpenPort: 53/tcp
    Service: domain (DNS/TCP)
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET6, socket.SOCK_STREAM).connect((host, port))
        socket.close()
        return True
    except socket.error as ex:
        socket.close()
        return False
