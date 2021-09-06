from .helpers import run_cli_async


async def get_speedtest_results() -> dict:
    result = await run_cli_async("speedtest -f json --accept-license")
    return result
