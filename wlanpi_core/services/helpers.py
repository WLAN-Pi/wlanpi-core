"""
shared resources between services
"""

import asyncio
import subprocess
from typing import Union

from wlanpi_core.models.runcommand_error import RunCommandError

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
            return_code=424, error_msg=f"'{cmd}' gave stderr response"
        )


def run_command(cmd) -> Union[str, None]:
    """
    Runs the given command, and handles errors and formatting.
    """
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL)
        return output.decode().strip()
    except subprocess.CalledProcessError:
        return None
