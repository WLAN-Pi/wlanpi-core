"""The network change lock (review of #286)."""

import pytest

from wlanpi_core.models.network_config_errors import ConfigBusyError
from wlanpi_core.utils import network_config as nc


def test_lock_is_not_reentrant():
    with nc.network_change_lock():
        with pytest.raises(ConfigBusyError):
            with nc.network_change_lock():
                pass


def test_lock_is_released_after_use():
    with nc.network_change_lock():
        pass
    with nc.network_change_lock():
        pass
