import asyncio
import sqlite3
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import aiosqlite
import pytest
import pytest_asyncio

import wlanpi_core.core.database as database_module
import wlanpi_core.core.token as token_module
from wlanpi_core.core.database import DatabaseManager
from wlanpi_core.core.repositories import TokenRepository
from wlanpi_core.core.token import AUTH_CLOCK_NOT_SET, TokenManager

BOOT_ID = "boot-a"
BOOTTIME = 1_000.0
WALL_TIME = 1_000_000.0


@pytest_asyncio.fixture
async def token_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(database_module, "DATABASE_PATH", str(tmp_path))
    monkeypatch.setattr(token_module, "current_boot_id", lambda: BOOT_ID)
    monkeypatch.setattr(token_module, "current_boottime", lambda: BOOTTIME)
    monkeypatch.setattr(token_module, "current_wall_time", lambda: WALL_TIME)
    monkeypatch.setattr(token_module.system_service, "get_hostname", lambda: "wlanpi")

    db_manager = DatabaseManager(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'tokens.db'}"
    )
    await db_manager.initialize_models()
    manager = TokenManager(SimpleNamespace(db_manager=db_manager))

    yield manager

    await db_manager.cleanup()


async def _rewrite_token(manager, token, *, updates=None, remove=()):
    async with manager.app_state.db_manager.session() as session:
        token_model = await TokenRepository(session).get_token_by_value(token)
        key = token_model.signing_key
        payload = dict(token_module.jwt.decode(token, key.key))
        payload.update(updates or {})
        for claim in remove:
            payload.pop(claim, None)
        replacement = token_module.jwt.encode(
            {"alg": "HS256", "kid": str(key.id)}, payload, key.key
        ).decode()
        token_model.token = replacement
        await session.commit()
    return replacement


async def _replace_stored_token(manager, token, replacement):
    async with manager.app_state.db_manager.session() as session:
        token_model = await TokenRepository(session).get_token_by_value(token)
        token_model.token = replacement
        await session.commit()


async def _decode_token(manager, token):
    async with manager.app_state.db_manager.session() as session:
        token_model = await TokenRepository(session).get_token_by_value(token)
        return token_module.jwt.decode(token, token_model.signing_key.key)


@pytest.mark.asyncio
async def test_issuance_uses_absolute_boot_expiry(token_manager):
    token = await token_manager.create_token(
        "claims", expires_delta=timedelta(seconds=60)
    )
    payload = await _decode_token(token_manager, token)

    assert payload["bid"] == BOOT_ID
    assert payload["bexp"] == BOOTTIME + 60
    assert payload["iat"] == WALL_TIME
    assert payload["exp"] == WALL_TIME + 60
    assert "upt" not in payload
    assert "ttl" not in payload


@pytest.mark.asyncio
async def test_verification_normalizes_bearer_whitespace(token_manager):
    token = await token_manager.create_token("whitespace")

    assert (await token_manager.verify_token(f"  {token}")).is_valid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("boottime", "is_valid"),
    [(BOOTTIME + 59.9, True), (BOOTTIME + 60, False), (BOOTTIME + 61, False)],
)
async def test_same_boot_expiry_boundary(
    token_manager, monkeypatch, boottime, is_valid
):
    token = await token_manager.create_token(
        "boundary", expires_delta=timedelta(seconds=60)
    )
    monkeypatch.setattr(token_module, "current_boottime", lambda: boottime)

    result = await token_manager.verify_token(token)

    assert result.is_valid is is_valid


@pytest.mark.asyncio
@pytest.mark.parametrize("wall_time", [1.0, WALL_TIME + 30 * 86400])
async def test_same_boot_ignores_wall_clock(token_manager, monkeypatch, wall_time):
    token = await token_manager.create_token(
        "wall-jump", expires_delta=timedelta(seconds=60)
    )
    monkeypatch.setattr(token_module, "current_wall_time", lambda: wall_time)

    assert (await token_manager.verify_token(token)).is_valid


@pytest.mark.asyncio
async def test_service_restart_on_same_boot_keeps_token(token_manager):
    token = await token_manager.create_token("restart")
    restarted = TokenManager(token_manager.app_state)

    assert (await restarted.verify_token(token)).is_valid


@pytest.mark.asyncio
async def test_issuance_reserves_write_lock_before_selecting_key(
    token_manager, monkeypatch
):
    await token_manager.create_token("race-setup")
    selected = asyncio.Event()
    release = asyncio.Event()
    original = token_manager._get_or_create_signing_key

    async def pause_after_selection(session):
        key = await original(session)
        selected.set()
        await release.wait()
        return key

    monkeypatch.setattr(
        token_manager, "_get_or_create_signing_key", pause_after_selection
    )
    issuance = asyncio.create_task(token_manager.create_token("race-setup"))
    try:
        await asyncio.wait_for(selected.wait(), timeout=1)
        database_path = token_manager.app_state.db_manager.engine.url.database
        async with aiosqlite.connect(database_path, timeout=0) as contender:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                await contender.execute("BEGIN IMMEDIATE")
    finally:
        release.set()
        await asyncio.wait_for(issuance, timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_cross_boot_and_legacy_tokens_use_wall_expiry(
    token_manager, monkeypatch, legacy
):
    token = await token_manager.create_token(
        "cross-boot", expires_delta=timedelta(seconds=60)
    )
    if legacy:
        token = await _rewrite_token(token_manager, token, remove=("bid", "bexp"))
    monkeypatch.setattr(token_module, "current_boot_id", lambda: "boot-b")
    monkeypatch.setattr(token_module, "current_wall_time", lambda: WALL_TIME + 59)
    assert (await token_manager.verify_token(token)).is_valid

    monkeypatch.setattr(token_module, "current_wall_time", lambda: WALL_TIME + 60)
    result = await token_manager.verify_token(token)
    assert not result.is_valid
    assert result.error == "Token expired"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_clock_lag_result_is_transient(token_manager, monkeypatch, legacy):
    token = await token_manager.create_token("clock-lag")
    if legacy:
        token = await _rewrite_token(token_manager, token, remove=("bid", "bexp"))
    monkeypatch.setattr(token_module, "current_boot_id", lambda: "boot-b")
    monkeypatch.setattr(
        token_module,
        "current_wall_time",
        lambda: WALL_TIME - token_module.CLOCK_SKEW_TOLERANCE_SEC - 1,
    )

    result = await token_manager.verify_token(token)
    assert not result.is_valid
    assert result.error == AUTH_CLOCK_NOT_SET

    monkeypatch.setattr(token_module, "current_wall_time", lambda: WALL_TIME)
    assert (await token_manager.verify_token(token)).is_valid


@pytest.mark.asyncio
async def test_clock_skew_boundary_is_not_clock_error(token_manager, monkeypatch):
    token = await token_manager.create_token("clock-boundary")
    monkeypatch.setattr(token_module, "current_boot_id", lambda: "boot-b")
    monkeypatch.setattr(
        token_module,
        "current_wall_time",
        lambda: WALL_TIME - token_module.CLOCK_SKEW_TOLERANCE_SEC,
    )

    assert (await token_manager.verify_token(token)).is_valid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "remove"),
    [
        ({}, ("bexp",)),
        ({"bid": 1}, ()),
        ({"bexp": "later"}, ()),
        ({"bexp": True}, ()),
        ({"bexp": float("inf")}, ()),
        ({"bid": "boot-b", "bexp": -1}, ()),
        ({"iat": True}, ()),
        ({"exp": float("nan")}, ()),
    ],
)
async def test_malformed_lifetime_claims_are_permanent_failures(
    token_manager, updates, remove
):
    token = await token_manager.create_token("malformed")
    token = await _rewrite_token(token_manager, token, updates=updates, remove=remove)

    result = await token_manager.verify_token(token)

    assert not result.is_valid
    assert result.error != AUTH_CLOCK_NOT_SET


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["revoke", "rotate"])
async def test_persisted_invalidation_precedes_clock_checks(
    token_manager, monkeypatch, action
):
    token = await token_manager.create_token("invalidated")
    if action == "revoke":
        await token_manager.revoke_token(token)
    else:
        await token_manager.rotate_key()
    boot_id = Mock(side_effect=AssertionError("clock must not be read"))
    monkeypatch.setattr(token_module, "current_boot_id", boot_id)

    result = await token_manager.verify_token(token)

    assert not result.is_valid
    boot_id.assert_not_called()


@pytest.mark.asyncio
async def test_bad_signature_precedes_clock_checks(token_manager, monkeypatch):
    token = await token_manager.create_token("bad-signature")
    tampered = f"{token.rsplit('.', 1)[0]}.AAAA"
    await _replace_stored_token(token_manager, token, tampered)
    boot_id = Mock(side_effect=AssertionError("clock must not be read"))
    monkeypatch.setattr(token_module, "current_boot_id", boot_id)

    result = await token_manager.verify_token(tampered)

    assert not result.is_valid
    boot_id.assert_not_called()


@pytest.mark.asyncio
async def test_revocation_is_immediate_and_idempotent(token_manager):
    token = await token_manager.create_token("revocation")
    assert (await token_manager.verify_token(token)).is_valid

    first = await token_manager.revoke_token(token)
    assert first["status"] == "success"
    result = await token_manager.verify_token(token)
    assert not result.is_valid
    assert result.error == "Token revoked"

    second = await token_manager.revoke_token(token)
    assert second["status"] == "info"


@pytest.mark.asyncio
async def test_expired_token_row_is_retained(token_manager, monkeypatch):
    token = await token_manager.create_token(
        "retained", expires_delta=timedelta(seconds=60)
    )
    monkeypatch.setattr(token_module, "current_boottime", lambda: BOOTTIME + 60)

    assert not (await token_manager.verify_token(token)).is_valid
    async with token_manager.app_state.db_manager.session() as session:
        assert await TokenRepository(session).get_token_by_value(token) is not None


@pytest.mark.asyncio
async def test_boot_source_failure_is_operational(token_manager, monkeypatch):
    token = await token_manager.create_token("boot-failure")
    monkeypatch.setattr(
        token_module, "current_boot_id", Mock(side_effect=OSError("no boot id"))
    )

    with pytest.raises(OSError, match="no boot id"):
        await token_manager.verify_token(token)


@pytest.mark.asyncio
async def test_boottime_failure_is_operational(token_manager, monkeypatch):
    token = await token_manager.create_token("boottime-failure")
    monkeypatch.setattr(
        token_module,
        "current_boottime",
        Mock(side_effect=OSError("no boottime")),
    )

    with pytest.raises(OSError, match="no boottime"):
        await token_manager.verify_token(token)


@pytest.mark.asyncio
async def test_database_failure_is_operational(token_manager, monkeypatch):
    token = await token_manager.create_token("database-failure")
    monkeypatch.setattr(
        token_manager.app_state.db_manager,
        "session",
        Mock(side_effect=RuntimeError("database unavailable")),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await token_manager.verify_token(token)


@pytest.mark.asyncio
async def test_unexpected_header_parser_failure_is_operational(
    token_manager, monkeypatch
):
    token = await token_manager.create_token("parser-failure")
    monkeypatch.setattr(
        token_module.json, "loads", Mock(side_effect=RuntimeError("parser failed"))
    )

    with pytest.raises(RuntimeError, match="parser failed"):
        await token_manager.verify_token(token)


@pytest.mark.asyncio
async def test_revoke_device_tokens_only_touches_that_device(token_manager):
    webui = await token_manager.create_token("wlanpi-webui")
    webui_2 = await token_manager.create_token("wlanpi-webui")
    other = await token_manager.create_token("mcp-client")

    assert await token_manager.revoke_device_tokens("wlanpi-webui") == 2
    assert await token_manager.revoke_device_tokens("wlanpi-webui") == 0

    for token in (webui, webui_2):
        assert (await token_manager.verify_token(token)).error == "Token revoked"
    assert (await token_manager.verify_token(other)).is_valid
