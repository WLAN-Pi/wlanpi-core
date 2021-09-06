import httpx
from httpx import Response

from wlanpi_core.models.validation_error import ValidationError

from .helpers import run_cli_async


async def get_neighbor_results():
    """
    Run `lldpcli show neighbors -f json` and return results
    ```
    """

    return await run_cli_async("/usr/sbin/lldpcli show neighbors -f json")


async def get_public_ip():
    url = "https://ifconfig.co/json"

    async with httpx.AsyncClient() as client:
        resp: Response = await client.get(url)
        if resp.status_code != 200:
            raise ValidationError(content=resp.text, status_code=resp.status_code)

    return resp.json()
