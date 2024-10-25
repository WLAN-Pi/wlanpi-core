import asyncio.subprocess
import logging
import subprocess
from asyncio.subprocess import Process
from io import StringIO
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
        logging.getLogger().warning(f"Command {cmd} being run as a shell script. This could present "
                                    f"an injection vulnerability. Consider whether you really need to do this.")
    else:
        cmd: list[str]
    with subprocess.Popen(
        cmd,
        shell=shell,
        stdin=subprocess.PIPE if input or isinstance(stdin, StringIO) else stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    ) as proc:
        if input:
            input_data = input.encode()
        elif isinstance(stdin, StringIO):
            input_data = stdin.read().encode()
        else:
            input_data = None
        stdout, stderr = proc.communicate(input=input_data)

        if raise_on_fail and proc.returncode != 0:
            raise RunCommandError(stderr.decode(), proc.returncode)
        return CommandResult(stdout.decode(), stderr.decode(), proc.returncode)


async def run_command_async(cmd: Union[list, str], input:Optional[str]=None, stdin:Optional[TextIO]=None, shell=False, raise_on_fail=True) -> CommandResult:
    """Run a single CLI command with asyncio.subprocess and returns the output"""

    # cannot have both input and STDIN, unless stdin is the constant for PIPE or /dev/null
    if input and stdin and not isinstance(stdin, int):
        raise RunCommandError(error_msg="You cannot use both 'input' and 'stdin' on the same call.", status_code=-1)

    # Prepare input data for communicate
    if input:
        input_data = input.encode()
    elif isinstance(stdin, StringIO):
        input_data = stdin.read().encode()
    else:
        input_data = None

    # asyncio.subprocess has different commands for shell and no shell.
    # Switch between them to keep a standard interface.
    if shell:
        cmd: str
        logging.getLogger().warning(f"Command {cmd} being run as a shell script. This could present "
                                    f"an injection vulnerability. Consider whether you really need to do this.")

        proc = await asyncio.subprocess.create_subprocess_shell(
                cmd,
                stdin=subprocess.PIPE if input or isinstance(stdin, StringIO) else stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
        )
        proc: Process
        stdout, stderr = await proc.communicate(input=input_data)
    else:
        cmd: list[str]
        proc =  await asyncio.subprocess.create_subprocess_exec(
                cmd[0],
                *cmd[1:],
                stdin=subprocess.PIPE if input or isinstance(stdin, StringIO) else stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
        )
        proc: Process
        stdout, stderr = await proc.communicate(input=input_data)

    if raise_on_fail and proc.returncode != 0:
        raise RunCommandError(error_msg=stderr.decode(), status_code=proc.returncode)
    return CommandResult(stdout.decode(), stderr.decode(), proc.returncode)
