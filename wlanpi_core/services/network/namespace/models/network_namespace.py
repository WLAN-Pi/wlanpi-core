import logging
import re
from typing import List

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.services.network.namespace.models.network_namespace_errors import (
    NetworkNamespaceError,
    NetworkNamespaceNotFoundError,
)
from wlanpi_core.utils.general import run_command

# log = logging.getLogger("uvicorn")


class NetworkNamespace:
    _static_logger = logging.getLogger("NetworkNamespace")

    def __init__(self, name: str):
        self.name = name
        self.creation_result = None
        self.log = logging.getLogger("NetworkNamespace")

        if not NetworkNamespace.namespace_exists(name):
            self.creation_result = NetworkNamespace.create(name)

    def get_interfaces(self) -> list:
        """
        Returns all interfaces that belong to this network namespace, a la ifconfig
        """
        return NetworkNamespace.get_interfaces_in_namespace(self.name)

    def get_processes(self) -> list:
        """
        Lists all processes currently running in a namespace
        """
        return NetworkNamespace.processes_using_namespace(self.name)

    def run_command(
        self, namespace_name: str, command: List[str], shell=False, raise_on_fail=True
    ) -> CommandResult:
        """
        Runs a command in the context of this network namespace
        """
        return NetworkNamespace.run_command_in_namespace(
            self.name, command, shell=shell, raise_on_fail=raise_on_fail
        )

    def destroy(self):
        """
        Destroys this network namespace, killing all processes inside and
        moving interfaces back to the root namespace as necessary.
        """
        return NetworkNamespace.destroy_namespace(self.name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.destroy()
        except NetworkNamespaceNotFoundError:
            # User may have already called destroy here.
            pass

    # Static methods

    @staticmethod
    def create(namespace_name: str) -> CommandResult:
        """
        Attempts to create a network namespace
        """
        return run_command(f"ip -j netns add {namespace_name}".split())

    @staticmethod
    def list_namespaces() -> list:
        """
        Lists all known network namespaces
        """
        result = run_command("ip -j netns list".split(), raise_on_fail=False)
        if not result.success:
            raise NetworkNamespaceError(f"Error listing namespaces: {result.error}")
        return result.output_from_json() or []

    @staticmethod
    def namespace_exists(namespace_name: str) -> bool:
        """
        Indicates if a network namespace exists
        """
        namespaces = NetworkNamespace.list_namespaces()
        return namespace_name in [ns["name"] for ns in namespaces]

    @staticmethod
    def get_interfaces_in_namespace(namespace_name: str) -> list:
        """
        Returns all interfaces that belong to a network namespace, a la ifconfig
        """
        return run_command(
            f"ip netns exec {namespace_name} jc ifconfig -a".split()
        ).output_from_json()

    @staticmethod
    def run_command_in_namespace(
        namespace_name: str, command: List[str], shell=False, raise_on_fail=True
    ) -> CommandResult:
        """
        Runs a command in the context of a network namespace
        """
        built_command = ["ip", "netns", "exec", namespace_name, *command]
        NetworkNamespace._static_logger.debug(f"Running command: {built_command}")
        return run_command(built_command, raise_on_fail=raise_on_fail, shell=shell)

    @staticmethod
    def destroy_namespace(namespace_name: str):
        """
        Destroys a network namespace, killing all processes inside and
        moving interfaces back to the root namespace as necessary.
        """
        if not NetworkNamespace.namespace_exists(namespace_name):
            raise NetworkNamespaceNotFoundError()
        NetworkNamespace._static_logger.info(
            f"Asked to destroy namespace {namespace_name}"
        )
        NetworkNamespace._static_logger.info(
            f"Killing old processes in {namespace_name}"
        )

        # This particular subcommand doesn't support JSON mode.
        pids = NetworkNamespace.processes_using_namespace(namespace_name)

        for pid in pids:
            NetworkNamespace._static_logger.info(f"Killing process {pid}")
            res = run_command(
                f"ip netns exec {namespace_name} kill {pid}".split(),
                raise_on_fail=False,
            )
            if not res.success:
                raise NetworkNamespaceError(
                    f"Failed to kill process {pid} while destroying namespace {namespace_name}"
                )

        NetworkNamespace._static_logger.info(
            f"Moving interfaces out of {namespace_name}"
        )

        for interface in NetworkNamespace.get_interfaces_in_namespace(namespace_name):
            print(interface)
            NetworkNamespace._static_logger.info(
                f"Moving interface {interface} out of {namespace_name}"
            )

            if interface["name"].startswith("wlan"):
                # Get phy num of interface
                res = run_command(
                    f"ip netns exec {namespace_name} iw dev {interface['name']} info".split()
                )
                phynum = re.findall(r"wiphy ([0-9]+)", res.output)[0]
                phy = f"phy{phynum}"

                res = run_command(
                    f"ip netns exec {namespace_name} iw phy {phy} set netns 1".split(),
                    raise_on_fail=False,
                )
                if not res.success:
                    raise NetworkNamespaceError(
                        f"Failed to move wireless interface {interface['name']} to default namespace: {res.error}"
                    )

            elif interface["name"].startswith("eth"):
                res = run_command(
                    f"ip netns exec {namespace_name} ip link set '{interface['name']}' netns 1".split(),
                    raise_on_fail=False,
                )
                if not res.success:
                    raise NetworkNamespaceError(
                        f"Failed to move wired interface {interface['name']} to default namespace: {res.error}"
                    )

            elif interface["name"].startswith("lo"):
                NetworkNamespace._static_logger.info(
                    f"Ignoring loopback interface {interface['name']}"
                )
            else:
                raise NetworkNamespaceError(
                    f"Don't know how to move {interface['name']} to default namespace."
                )

        NetworkNamespace._static_logger.info(f"Deleting namespace {namespace_name}")
        res = run_command(f"ip netns del {namespace_name}".split(), raise_on_fail=False)
        if not res.success:
            raise NetworkNamespaceError(
                f"Unable to destroy namespace {namespace_name} {res.error}"
            )

    @staticmethod
    def processes_using_namespace(namespace_name: str):
        """
        Lists all processes currently running in a namespace
        """
        result = run_command(
            f"ip netns pids {namespace_name}".split(), raise_on_fail=False
        )
        if not result.success:
            raise NetworkNamespaceError(
                f"Error getting namespace processes: {result.error}"
            )
        return [int(x) for x in filter(None, result.output.split("\n") or [])]
