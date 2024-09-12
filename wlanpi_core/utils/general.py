import subprocess

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError


def run_command(cmd: list, shell=False, raise_on_fail=True) -> CommandResult:
    """Run a single CLI command with subprocess and returns the output"""
    # print("Running command:", cmd)
    cp = subprocess.run(
        cmd,
        encoding="utf-8",
        shell=shell,
        check=False,
        capture_output=True,
    )
    if raise_on_fail and cp.returncode != 0:
        raise RunCommandError(cp.stderr, cp.returncode)
    return CommandResult(cp.stdout, cp.stderr, cp.returncode)
