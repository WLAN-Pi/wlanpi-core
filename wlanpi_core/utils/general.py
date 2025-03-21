import asyncio.subprocess
import logging
import shlex
import subprocess
import threading
import time
from asyncio.subprocess import Process
from datetime import datetime, timezone
from io import StringIO
from typing import Any, Dict, Generic, Optional, TextIO, Type, TypeVar, Union

from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError

log = get_logger(__name__)

T = TypeVar("T")


def run_command(
    cmd: Union[list, str],
    input: Optional[str] = None,
    stdin: Optional[TextIO] = None,
    shell=False,
    raise_on_fail=True,
) -> CommandResult:
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
        raise RunCommandError(
            error_msg="You cannot use both 'input' and 'stdin' on the same call.",
            return_code=-1,
        )

    # Todo: explore using shlex to always split to protect against injections
    if shell:
        # If a list was passed in shell mode, safely join using shlex to protect against injection.
        if isinstance(cmd, list):
            cmd: list
            cmd: str = shlex.join(cmd)
        cmd: str
        logging.getLogger().warning(
            f"Command {cmd} being run as a shell script. This could present "
            f"an injection vulnerability. Consider whether you really need to do this."
        )
    else:
        # If a string was passed in non-shell mode, safely split it using shlex to protect against injection.
        if isinstance(cmd, str):
            cmd: str
            cmd: list[str] = shlex.split(cmd)
        cmd: list[str]
    with subprocess.Popen(
        cmd,
        shell=shell,
        stdin=subprocess.PIPE if input or isinstance(stdin, StringIO) else stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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


async def run_command_async(
    cmd: Union[list, str],
    input: Optional[str] = None,
    stdin: Optional[TextIO] = None,
    shell=False,
    raise_on_fail=True,
) -> CommandResult:
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
        raise RunCommandError(
            error_msg="You cannot use both 'input' and 'stdin' on the same call.",
            return_code=-1,
        )

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
        logging.getLogger().warning(
            f"Command {cmd} being run as a shell script. This could present "
            f"an injection vulnerability. Consider whether you really need to do this."
        )

        proc = await asyncio.subprocess.create_subprocess_shell(
            cmd,
            stdin=subprocess.PIPE if input or isinstance(stdin, StringIO) else stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        proc: Process
        stdout, stderr = await proc.communicate(input=input_data)
    else:
        # If a string was passed in non-shell mode, safely split it using shlex to protect against injection.
        if isinstance(cmd, str):
            cmd: str
            cmd: list[str] = shlex.split(cmd)
        cmd: list[str]
        proc = await asyncio.subprocess.create_subprocess_exec(
            cmd[0],
            *cmd[1:],
            stdin=subprocess.PIPE if input or isinstance(stdin, StringIO) else stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        proc: Process
        stdout, stderr = await proc.communicate(input=input_data)

    if raise_on_fail and proc.returncode != 0:
        raise RunCommandError(error_msg=stderr.decode(), return_code=proc.returncode)
    return CommandResult(stdout.decode(), stderr.decode(), proc.returncode)


def get_model_info() -> dict[str, str]:
    """Uses wlanpi-model cli command to get model info
    Returns:
        dictionary of model info
    Raises:
        RunCommandError: If the underlying command failed.
    """

    model_info = run_command(["wlanpi-model"]).stdout.split("\n")
    split_model_info = [a.split(":", 1) for a in model_info if a.strip() != ""]
    model_dict = {}
    for a, b in split_model_info:
        model_dict[a.strip()] = b.strip()
    return model_dict


def get_uptime() -> dict[str, str]:
    """Gets the system uptime using jc and the uptime command.
    Returns:
        dictionary of uptime info
    Raises:
        RunCommandError: If the underlying command failed.
    """
    cmd = "jc uptime"
    return run_command(cmd.split(" ")).output_from_json()


def get_hostname() -> str:
    """Gets the system hostname using hostname command.
    Returns:
        The system hostname as a string
    Raises:
        RunCommandError: If the underlying command failed.
    """
    return run_command(["hostname"]).stdout.strip("\n ")


def get_current_unix_timestamp() -> float:
    """Gets the current unix timestamp in milliseconds
    Returns:
        The current unix timestamp in milliseconds
    """
    ms = datetime.now()
    return time.mktime(ms.timetuple()) * 1000


def to_timestamp(dt: Optional[Union[datetime, str, int, float]]) -> Optional[int]:
    """
    Convert various datetime formats to Unix timestamp

    Args:
        dt: Input datetime (can be datetime object, ISO string, or timestamp)

    Returns:
        int: Unix timestamp in seconds
    """
    if dt is None:
        return None

    try:
        if isinstance(dt, (int, float)):
            return int(dt)
        elif isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))

        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())

        raise ValueError(f"Unsupported datetime format: {type(dt)}")
    except Exception:
        log.exception("Failed to convert to timestamp")
        return None


def from_timestamp(ts: Optional[Union[int, float, str]]) -> Optional[datetime]:
    """
    Convert Unix timestamp to UTC datetime

    Args:
        ts: Unix timestamp (seconds since epoch)

    Returns:
        datetime: UTC datetime object
    """
    if ts is None:
        return None

    try:
        if isinstance(ts, str):
            ts = float(ts)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        log.exception(f"Failed to convert from timestamp")
        return None


class SingletonMeta(type, Generic[T]):
    _instances: Dict[Type[Any], Any] = {}
    _lock = threading.Lock()

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

    @classmethod
    def reset_instance(cls, singleton_cls: Type[T]) -> None:
        """Reset the singleton instance for the given class."""
        with cls._lock:
            if singleton_cls in cls._instances:
                del cls._instances[singleton_cls]
