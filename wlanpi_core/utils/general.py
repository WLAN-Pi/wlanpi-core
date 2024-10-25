import asyncio.subprocess
import logging
import subprocess
from asyncio.subprocess import Process
from typing import Union, Optional, TextIO

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError


def run_command(cmd: Union[list, str], input:Optional[str]=None, stdin:Optional[TextIO]=None, shell=False, raise_on_fail=True) -> CommandResult:
    """Run a single CLI command with subprocess and returns the output"""

    # cannot have both input and STDIN, unless stdin is the constant for PIPE or /dev/null
    if input and stdin and not isinstance(stdin, int):
        raise RunCommandError(error_msg="You cannot use both 'input' and 'stdin' on the same call.", status_code=-1)

    if shell:
        cmd: str
        logging.getLogger().warning(f"Command {cmd} being run as a shell script. This could present"
                                    f"an injection vulnerability. Consider whether you really need to do this.")
    else:
        cmd: list[str]
    cp = subprocess.run(
        cmd,
        input=input,
        stdin=stdin,
        encoding="utf-8",
        shell=shell,
        check=False,
        capture_output=True,
    )

    if raise_on_fail and cp.returncode != 0:
        raise RunCommandError(cp.stderr, cp.returncode)
    return CommandResult(cp.stdout, cp.stderr, cp.returncode)


async def run_command_async(cmd: Union[list, str], input:Optional[str]=None, stdin:Optional[TextIO]=None, shell=False, raise_on_fail=True) -> CommandResult:
    """Run a single CLI command with asyncio.subprocess and returns the output"""

    # cannot have both input and STDIN, unless stdin is the constant for PIPE or /dev/null
    if input and stdin and not isinstance(stdin, int):
        raise RunCommandError(error_msg="You cannot use both 'input' and 'stdin' on the same call.", status_code=-1)

    # asyncio.subprocess has different commands for shell and no shell.
    # Switch between them to keep a standard interface.
    if shell:
        cmd: str
        logging.getLogger().warning(f"Command {cmd} being run as a shell script. This could present"
                                    f"an injection vulnerability. Consider whether you really need to do this.")

        with asyncio.subprocess.create_subprocess_shell(
                cmd,
                stdin=asyncio.subprocess.PIPE if input else stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
        ) as proc:
            proc: Process
            stdout, stderr = await proc.communicate(input=input.encode() if input else None)
    else:
        cmd: list[str]
        with asyncio.subprocess.create_subprocess_exec(
                cmd[0],
                *cmd[1:],
                stdin=asyncio.subprocess.PIPE if input else stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
        ) as proc:
            proc: Process
            stdout, stderr = await proc.communicate(input=input.encode() if input else None)

    if raise_on_fail and proc.returncode != 0:
        raise RunCommandError(error_msg=stderr.decode(), status_code=proc.returncode)
    return CommandResult(stdout.decode(), stderr.decode(), proc.returncode)
