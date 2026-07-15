"""Tests for lazy, bounded systemd D-Bus access."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from dbus.exceptions import DBusException

from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.services import system_service


def test_app_import_does_not_connect_to_system_bus():
    """Constructing the FastAPI app must not require a live system bus."""
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(repo_root), existing_pythonpath) if part
    )
    code = """
import dbus

def fail_if_called(*args, **kwargs):
    raise AssertionError("SystemBus opened during app import")

dbus.SystemBus = fail_if_called
import wlanpi_core.asgi
import wlanpi_core.services.network_service
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr


def test_legacy_network_dbus_manager_is_lazy(mocker):
    from wlanpi_core.services.network_service import AsyncDBusManager

    bus = MagicMock()
    connect = mocker.patch("dbus.SystemBus", return_value=bus)

    manager = AsyncDBusManager()

    connect.assert_not_called()
    assert manager.bus is bus
    assert manager.bus is bus
    connect.assert_called_once_with()


def test_system_bus_connection_failure_is_a_scoped_503(mocker):
    system_service._reset_systemd_client()
    connect = mocker.patch.object(
        system_service,
        "SystemBus",
        side_effect=DBusException(
            "Failed to connect to socket",
            name="org.freedesktop.DBus.Error.FileNotFound",
        ),
    )

    try:
        with pytest.raises(ValidationError) as exc_info:
            system_service.check_service_status("iperf")
    finally:
        system_service._reset_systemd_client()

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_msg == "System D-Bus is unavailable"
    connect.assert_called_once_with()


def test_systemd_client_is_created_lazily_and_cached(mocker):
    system_service._reset_systemd_client()
    bus = MagicMock()
    systemd_proxy = MagicMock()
    manager = MagicMock()
    bus.get_object.return_value = systemd_proxy
    connect = mocker.patch.object(system_service, "SystemBus", return_value=bus)
    interface = mocker.patch.object(system_service, "Interface", return_value=manager)

    try:
        assert system_service._systemd_client is None
        first = system_service._get_systemd_client()
        second = system_service._get_systemd_client()
    finally:
        system_service._reset_systemd_client()

    assert first == (bus, manager)
    assert second == first
    connect.assert_called_once_with()
    bus.get_object.assert_called_once_with(
        system_service._SYSTEMD_BUS_NAME,
        system_service._SYSTEMD_OBJECT_PATH,
    )
    interface.assert_called_once_with(
        systemd_proxy,
        dbus_interface=system_service._SYSTEMD_MANAGER_INTERFACE,
    )


def test_disconnected_system_bus_is_rebuilt_on_next_request(mocker):
    system_service._reset_systemd_client()
    disconnected = DBusException(
        "Connection is closed",
        name="org.freedesktop.DBus.Error.Disconnected",
    )

    first_bus = MagicMock()
    first_manager = MagicMock()
    first_manager.RestartUnit.side_effect = disconnected

    second_bus = MagicMock()
    second_manager = MagicMock()
    second_manager.GetUnit.return_value = "/org/freedesktop/systemd1/unit/iperf"
    service_properties = MagicMock()
    service_properties.Get.side_effect = ["loaded", "active"]

    connect = mocker.patch.object(
        system_service,
        "SystemBus",
        side_effect=[first_bus, second_bus],
    )
    mocker.patch.object(
        system_service,
        "Interface",
        side_effect=[first_manager, second_manager, service_properties],
    )

    try:
        with pytest.raises(ValidationError) as exc_info:
            system_service.restart_service("iperf")

        assert exc_info.value.status_code == 503
        assert system_service._systemd_client is None
        assert system_service.restart_service("iperf") is True
    finally:
        system_service._reset_systemd_client()

    assert connect.call_count == 2
    first_manager.RestartUnit.assert_called_once_with(
        "iperf.service",
        "replace",
        timeout=system_service._SYSTEMD_DBUS_TIMEOUT_SEC,
    )
    second_manager.RestartUnit.assert_called_once_with(
        "iperf.service",
        "replace",
        timeout=system_service._SYSTEMD_DBUS_TIMEOUT_SEC,
    )


def test_systemd_dbus_calls_are_serialized(mocker):
    bus = MagicMock()
    manager = MagicMock()
    service_properties = MagicMock()
    manager.GetUnit.return_value = "/org/freedesktop/systemd1/unit/iperf"
    service_properties.Get.side_effect = lambda _interface, name, **_kwargs: (
        "loaded" if name == "LoadState" else "active"
    )
    mocker.patch.object(
        system_service,
        "_get_systemd_client",
        return_value=(bus, manager),
    )
    mocker.patch.object(system_service, "Interface", return_value=service_properties)

    call_state_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0

    def delayed_get_unit(*_args, **_kwargs):
        nonlocal active_calls, max_active_calls
        with call_state_lock:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
        try:
            time.sleep(0.025)
            return "/org/freedesktop/systemd1/unit/iperf"
        finally:
            with call_state_lock:
                active_calls -= 1

    manager.GetUnit.side_effect = delayed_get_unit

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(system_service.check_service_status, ["iperf", "iperf"])
        )

    assert results == [True, True]
    assert max_active_calls == 1
