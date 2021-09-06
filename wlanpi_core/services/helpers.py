import asyncio

from wlanpi_core.models.runcommand_error import RunCommandError


async def run_cli_async(cmd: str) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode == 0:
        if stdout:
            return stdout.decode()

    if stderr:
        raise RunCommandError(
            status_code=424, error_msg=f"'{cmd}' gave stderr response"
        )
