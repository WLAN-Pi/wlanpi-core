"""
shared resources between services
"""

import asyncio
import logging

from wlanpi_core.core.config import settings
from wlanpi_core.models.runcommand_error import RunCommandError

log = logging.getLogger("uvicorn")


def debug_print(message, level):
    """
    Logs a message based on the global debug level.

    :param message: The message to be printed.
    :param level: The level of the message (e.g., 1 for low, 2 for medium, 3 for high).
    """
    if settings.DEBUGGING:
        log.debug(message)


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
