import asyncio.subprocess
import logging
import shlex
import subprocess
from asyncio.subprocess import Process
from io import StringIO
from typing import Union, Optional, TextIO

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError


def run_command(cmd: Union[list, str], input:Optional[str]=None, stdin:Optional[TextIO]=None, shell=False, raise_on_fail=True) -> CommandResult:
    """Run a single CLI command with subprocess and returns the output"""
    """
    This function executes a single CLI command using the the built-in subprocess module.
    
    Args:
        cmd: The command to be executed. It can be a string or a list, it will be converted to the appropriate form by shlex.
             If it's a string, the command will be executed with its arguments as separate words,
             unless `shell=True` is specified.
        input: Optional input string that will be fed to the process's stdin.
              If provided and stdin=None, then this string will be used for stdin.
        stdin: Optional TextIO object that will be fed to the process's stdin.
              If None, then `input` or `stdin` will be used instead (if any).
        shell: Whether to execute the command using a shell or not. Default is False.
               If True, then the entire command string will be executed in a shell.
               Otherwise, the command and its arguments are executed separately.
        raise_on_fail: Whether to raise an error if the command fails or not. Default is True.
    
    Returns:
        A CommandResult object containing the output of the command, along with a boolean indicating
        whether the command was successful or not.
    
    Raises:
        RunCommandError: If `raise_on_fail=True` and the command failed.
    """


    # cannot have both input and STDIN, unless stdin is the constant for PIPE or /dev/null
    if input and stdin and not isinstance(stdin, int):
        raise RunCommandError(error_msg="You cannot use both 'input' and 'stdin' on the same call.", return_code=-1)

    # Todo: explore using shlex to always split to protect against injections
    if shell:
        # If a list was passed in shell mode, safely join using shlex to protect against injection.
        if isinstance(cmd, list):
            cmd: list
            cmd: str = shlex.join(cmd)
        cmd: str
        logging.getLogger().warning(f"Command {cmd} being run as a shell script. This could present "
                                    f"an injection vulnerability. Consider whether you really need to do this.")
    else:
        # If a string was passed in non-shell mode, safely split it using shlex to protect against injection.
        if isinstance(cmd, str):
            cmd:str
            cmd:list[str] = shlex.split(cmd)
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
    """Run a single CLI command with subprocess and returns the output"""
    """
    This function executes a single CLI command using the the built-in subprocess module.
    
    Args:
        cmd: The command to be executed. It can be a string or a list, it will be converted to the appropriate form by shlex.
             If it's a string, the command will be executed with its arguments as separate words,
             unless `shell=True` is specified.
        input: Optional input string that will be fed to the process's stdin.
              If provided and stdin=None, then this string will be used for stdin.
        stdin: Optional TextIO object that will be fed to the process's stdin.
              If None, then `input` or `stdin` will be used instead (if any).
        shell: Whether to execute the command using a shell or not. Default is False.
               If True, then the entire command string will be executed in a shell.
               Otherwise, the command and its arguments are executed separately.
        raise_on_fail: Whether to raise an error if the command fails or not. Default is True.
    
    Returns:
        A CommandResult object containing the output of the command, along with a boolean indicating
        whether the command was successful or not.
    
    Raises:
        RunCommandError: If `raise_on_fail=True` and the command failed.
    """

    # cannot have both input and STDIN, unless stdin is the constant for PIPE or /dev/null
    if input and stdin and not isinstance(stdin, int):
        raise RunCommandError(error_msg="You cannot use both 'input' and 'stdin' on the same call.", return_code=-1)

    # Prepare input data for communicate
    if input:
        input_data = input.encode()
    elif isinstance(stdin, StringIO):
        input_data = stdin.read().encode()
    else:
        input_data = None

    # Todo: explore using shlex to always split to protect against injections

    # asyncio.subprocess has different commands for shell and no shell.
    # Switch between them to keep a standard interface.
    if shell:
        # If a list was passed in shell mode, safely join using shlex to protect against injection.
        if isinstance(cmd, list):
            cmd: list
            cmd: str = shlex.join(cmd)
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
        # If a string was passed in non-shell mode, safely split it using shlex to protect against injection.
        if isinstance(cmd, str):
            cmd: str
            cmd: list[str] = shlex.split(cmd)
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
        raise RunCommandError(error_msg=stderr.decode(), return_code=proc.returncode)
    return CommandResult(stdout.decode(), stderr.decode(), proc.returncode)
