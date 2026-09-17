from types import SimpleNamespace

import pytest

from wlanpi_core import app as app_module


@pytest.mark.asyncio
async def test_token_manager_starts_without_purge_worker(monkeypatch):
    token_manager = object()
    monkeypatch.setattr(app_module, "TokenManager", lambda _state: token_manager)
    app = SimpleNamespace(state=SimpleNamespace())

    assert await app_module.InitializationManager(app)._initialize_token_manager()
    assert app.state.token_manager is token_manager
    assert not hasattr(app.state, "token_purge_task")
