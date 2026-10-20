"""
Core namespace functionality for network namespace operations.

This package provides focused modules for namespace lifecycle, interface management,
and process management, following the pattern established by core/ and profiler/ folders.
"""

from wlanpi_core.namespaces.apps import (
    get_app_command,
    start_app_in_namespace,
    stop_app_in_namespace,
)
from wlanpi_core.namespaces.interfaces import (
    get_interfaces_in_namespace,
    move_interface_to_namespace,
    move_interface_to_root,
)
from wlanpi_core.namespaces.namespace import (
    create_namespace,
    delete_namespace,
    list_namespaces,
    namespace_exists,
)
from wlanpi_core.namespaces.processes import (
    get_processes_in_namespace,
)

__all__ = [
    "create_namespace",
    "delete_namespace",
    "get_app_command",
    "get_interfaces_in_namespace",
    "get_processes_in_namespace",
    "list_namespaces",
    "move_interface_to_namespace",
    "move_interface_to_root",
    "namespace_exists",
    "start_app_in_namespace",
    "stop_app_in_namespace",
]
