"""Fail-loud critical initialization (PR #157)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wlanpi_core import app as app_module
from wlanpi_core.app import CriticalInitializationError, InitializationManager

# Captured at import time, before the autouse mock_app_initialization fixture
# replaces the class attribute for the rest of the suite.
_REAL_INITIALIZE_COMPONENTS = InitializationManager.initialize_components


async def test_initialize_components_fails_loud_when_system_not_ready(monkeypatch):
    """A failed readiness check must raise so the ASGI lifespan fails.

    systemd then sees a failed startup instead of serving half-initialized.
    """
    # Restore the real method over the autouse fixture's stub for this test.
    monkeypatch.setattr(
        app_module.InitializationManager,
        "initialize_components",
        _REAL_INITIALIZE_COMPONENTS,
    )
    manager = InitializationManager(MagicMock())

    async def _not_ready():
        return False

    monkeypatch.setattr(manager, "check_system_readiness", _not_ready)

    with pytest.raises(CriticalInitializationError, match="System not ready"):
        await manager.initialize_components()


async def test_token_manager_init_revokes_pam_client_tokens(monkeypatch):
    """Tokens minted for wlanpi-webui by any bearer before the fix must die."""
    revoke = AsyncMock(return_value=2)
    monkeypatch.setattr(
        app_module,
        "TokenManager",
        lambda state: MagicMock(revoke_device_tokens=revoke),
    )
    manager = InitializationManager(MagicMock())

    assert await manager._initialize_token_manager() is True
    revoke.assert_awaited_once_with("wlanpi-webui")


async def test_pam_client_token_revocation_failure_never_blocks_startup(
    monkeypatch,
):
    revoke = AsyncMock(side_effect=RuntimeError("database locked"))
    monkeypatch.setattr(
        app_module,
        "TokenManager",
        lambda state: MagicMock(revoke_device_tokens=revoke),
    )
    manager = InitializationManager(MagicMock())

    assert await manager._initialize_token_manager() is True
