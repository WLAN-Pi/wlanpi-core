from .helpers import run_cli_async


async def get_neighbor_results():
    """
    Run `lldpcli show neighbors -f json` and return results
    """

    return await run_cli_async("/usr/sbin/lldpcli show neighbors -f json")
