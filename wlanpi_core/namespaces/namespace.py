"""Create, list, check, and delete network namespaces."""

import logging
from typing import Any

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.network.namespace.namespace_errors import (
    NetworkNamespaceError,
    NetworkNamespaceNotFoundError,
)
from wlanpi_core.utils.general import run_command

log = logging.getLogger(__name__)


def create_namespace(namespace_name: str, use_sudo: bool = True) -> CommandResult:
    """Create a network namespace; raise NetworkNamespaceError on failure."""
    if not namespace_name or not namespace_name.strip():
        raise ValueError("namespace_name cannot be empty")

    cmd = ["ip", "netns", "add", namespace_name]
    if use_sudo:
        cmd = ["sudo", *cmd]

    log.info(f"Creating namespace: {namespace_name}")
    try:
        result = run_command(cmd, raise_on_fail=True)
        log.info(f"Namespace {namespace_name} created successfully")
        return result
    except Exception as e:
        log.error(f"Failed to create namespace {namespace_name}: {e}")
        raise NetworkNamespaceError(
            f"Failed to create namespace {namespace_name}: {e}"
        ) from None


def delete_namespace(
    namespace_name: str, use_sudo: bool = True, raise_on_fail: bool = True
) -> CommandResult:
    """Delete a network namespace.

    Raises:
        NetworkNamespaceNotFoundError: If it does not exist and raise_on_fail.
        NetworkNamespaceError: If deletion fails and raise_on_fail.
    """
    if not namespace_name or not namespace_name.strip():
        raise ValueError("namespace_name cannot be empty")

    if not namespace_exists(namespace_name):
        if raise_on_fail:
            raise NetworkNamespaceNotFoundError(
                f"Namespace {namespace_name} does not exist"
            )
        log.warning(f"Attempted to delete non-existent namespace: {namespace_name}")
        return CommandResult("", f"Namespace {namespace_name} does not exist", 1)

    cmd = ["ip", "netns", "delete", namespace_name]
    if use_sudo:
        cmd = ["sudo", *cmd]

    log.info(f"Deleting namespace: {namespace_name}")
    try:
        result = run_command(cmd, raise_on_fail=raise_on_fail)
        if result.return_code == 0:
            log.info(f"Namespace {namespace_name} deleted successfully")
        return result
    except Exception as e:
        log.error(f"Failed to delete namespace {namespace_name}: {e}")
        if raise_on_fail:
            raise NetworkNamespaceError(
                f"Failed to delete namespace {namespace_name}: {e}"
            ) from None
        return CommandResult("", str(e), 1)


def list_namespaces(use_json: bool = False) -> list[Any]:
    """Return namespace names, or `ip -j` dicts with use_json; raise NetworkNamespaceError on failure."""
    cmd = ["ip", "netns", "list"]
    if use_json:
        cmd = ["ip", "-j", "netns", "list"]

    log.debug("Listing network namespaces")
    try:
        result = run_command(cmd, raise_on_fail=False)
        if result.return_code != 0:
            raise NetworkNamespaceError(f"Error listing namespaces: {result.stderr}")

        if use_json:
            try:
                parsed = result.output_from_json()
                return parsed if isinstance(parsed, list) else []
            except Exception as e:
                log.warning(
                    f"Failed to parse JSON output: {e}, falling back to text parsing"
                )
                use_json = False

        if not use_json:
            # Parse text output: "namespace_name (id: N)" or just "namespace_name"
            namespaces = []
            for line in result.stdout.strip().splitlines():
                if line.strip():
                    namespace_name = line.split()[0]
                    namespaces.append(namespace_name)
            return namespaces

        return []
    except Exception as e:
        log.error(f"Failed to list namespaces: {e}")
        raise NetworkNamespaceError(f"Failed to list namespaces: {e}") from None


def namespace_exists(namespace_name: str) -> bool:
    """Return whether the namespace exists; False when listing fails."""
    if not namespace_name or not namespace_name.strip():
        return False

    try:
        namespaces = list_namespaces()
        return namespace_name in namespaces
    except NetworkNamespaceError:
        return False
