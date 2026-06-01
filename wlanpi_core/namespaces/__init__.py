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
    kill_processes_in_namespace,
)

__all__ = [
    # Namespace lifecycle
    "create_namespace",
    "delete_namespace",
    "list_namespaces",
    "namespace_exists",
    # Interface management
    "get_interfaces_in_namespace",
    "move_interface_to_namespace",
    "move_interface_to_root",
    # Process management
    "get_processes_in_namespace",
    "kill_processes_in_namespace",
    # App management
    "get_app_command",
    "start_app_in_namespace",
    "stop_app_in_namespace",
]
