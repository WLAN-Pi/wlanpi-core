from unittest.mock import patch

import pytest

from wlanpi_core.services.network_service import AsyncDBusManager


class MockDBusConnection:
    def __init__(self):
        self.signals = {}
        self.read_called = 0

    def add_signal_receiver(self, callback, dbus_interface, signal_name):
        key = f"{dbus_interface}:{signal_name}"
        self.signals[key] = callback

        class MockHandler:
            def remove(self):
                pass

        return MockHandler()

    def iterate_read(self):
        self.read_called += 1


@pytest.fixture
def mock_dbus_bus():
    with patch("dbus.SystemBus") as mock_bus:
        mock_connection = MockDBusConnection()
        mock_bus.return_value = mock_connection
        yield mock_connection


@pytest.mark.asyncio
async def test_add_signal_receiver(mock_dbus_bus):
    """Test adding a signal receiver"""
    manager = AsyncDBusManager()

    def test_callback(arg):
        pass

    handler = manager.add_signal_receiver(
        test_callback, dbus_interface="test.interface", signal_name="TestSignal"
    )

    assert len(manager.signal_handlers) == 1
    assert mock_dbus_bus.signals.get("test.interface:TestSignal") == test_callback


@pytest.mark.asyncio
async def test_run_with_timeout_success(mock_dbus_bus):
    """Test run_with_timeout with successful condition"""
    manager = AsyncDBusManager()

    result = await manager.run_with_timeout(lambda: True, timeout=1)

    assert result is True

    assert mock_dbus_bus.read_called < 3


@pytest.mark.asyncio
async def test_run_with_timeout_timeout(mock_dbus_bus):
    """Test run_with_timeout with timeout"""
    manager = AsyncDBusManager()

    result = await manager.run_with_timeout(lambda: False, timeout=0.5)

    assert result is False

    assert mock_dbus_bus.read_called > 0


@pytest.mark.asyncio
async def test_run_with_timeout_condition_change(mock_dbus_bus):
    """Test run_with_timeout with condition that changes during execution"""
    manager = AsyncDBusManager()

    check_count = 0

    def condition():
        nonlocal check_count
        check_count += 1
        return check_count >= 3

    result = await manager.run_with_timeout(condition, timeout=2)

    assert result is True
    assert check_count >= 3
    assert mock_dbus_bus.read_called >= 2
