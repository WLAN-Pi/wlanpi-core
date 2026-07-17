import asyncio
from types import SimpleNamespace

import pytest

from wlanpi_core import app as app_module


@pytest.mark.asyncio
async def test_token_purge_task_is_named_and_owned_by_app(monkeypatch):
    started = asyncio.Event()

    class FakeTokenManager:
        def __init__(self, _state):
            pass

        async def purge_expired_tokens(self):
            started.set()
            await asyncio.Event().wait()

    app = SimpleNamespace(state=SimpleNamespace())
    manager = app_module.InitializationManager(app)
    monkeypatch.setattr(app_module, "TokenManager", FakeTokenManager)

    assert await manager._initialize_token_manager() is True
    await started.wait()
    task = app.state.token_purge_task

    assert task.get_name() == "token-purge"
    assert not task.done()

    await app_module._stop_token_purge_task(app)
    assert task.cancelled()
    assert app.state.token_purge_task is None


@pytest.mark.asyncio
async def test_stop_token_purge_task_waits_for_cleanup():
    cleaned_up = asyncio.Event()

    async def worker():
        try:
            await asyncio.Event().wait()
        finally:
            cleaned_up.set()

    task = asyncio.create_task(worker())
    await asyncio.sleep(0)
    app = SimpleNamespace(state=SimpleNamespace(token_purge_task=task))

    await app_module._stop_token_purge_task(app)

    assert task.cancelled()
    assert cleaned_up.is_set()
