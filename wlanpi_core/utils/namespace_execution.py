"""Run commands in a network namespace or the root namespace."""

import logging

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils.general import run_command
from wlanpi_core.utils.validation import validate_namespace_name

log = logging.getLogger(__name__)


def ns_exec(
    cmd: list[str],
    namespace: str | None = None,
    no_output: bool = False,
    raise_on_fail: bool = True,
) -> CommandResult:
    """Run `cmd` under sudo, inside `namespace` via `ip netns exec` when given.

    `no_output` suppresses debug logging of the output.

    Raises:
        RunCommandError: If `raise_on_fail` and the command fails.
    """
    if namespace is None:
        full_cmd = ["sudo", *cmd]
    else:
        namespace = validate_namespace_name(namespace)
        full_cmd = ["sudo", "ip", "netns", "exec", namespace, *cmd]

    log.debug(f"Executing in namespace '{namespace or 'root'}': {' '.join(full_cmd)}")

    try:
        result = run_command(full_cmd, raise_on_fail=raise_on_fail)

        if not no_output:
            log.debug(f"stdout: {result.stdout}")
            log.debug(f"stderr: {result.stderr}")
            log.debug(f"return_code: {result.return_code}")

        return result
    except RunCommandError as e:
        log.error(
            f"Command failed in namespace '{namespace or 'root'}': "
            f"{' '.join(cmd)} - {e}"
        )
        raise
    except Exception as e:
        log.error(
            f"Unexpected error executing command in namespace '{namespace or 'root'}': "
            f"{' '.join(cmd)} - {e}"
        )
        raise


def netns_prefix(namespace: str | None) -> list[str]:
    """Command prefix that runs a command in ``namespace``; empty for root."""
    if namespace is None:
        return []
    return ["ip", "netns", "exec", validate_namespace_name(namespace)]
