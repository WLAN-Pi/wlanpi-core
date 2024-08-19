"""
shared resources between services
"""

import asyncio
import subprocess

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
            status_code=424, error_msg=f"'{cmd}' gave stderr response"
        )
        
        
def run_command(cmd):
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL)
        return output.decode().strip()
    except subprocess.CalledProcessError:
        return None
