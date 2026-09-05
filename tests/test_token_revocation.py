"""Revoked tokens must stop validating immediately, including via the
in-process token cache (the cache fast-path previously kept accepting them
until an unrelated cache clear or restart)."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio

import wlanpi_core.core.database as database_module
import wlanpi_core.core.token as token_module
from wlanpi_core.core.cache import SKeyCache, TokenCache
from wlanpi_core.core.database import DatabaseManager
from wlanpi_core.core.token import TokenManager


@pytest_asyncio.fixture
async def token_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(database_module, "DATABASE_PATH", str(tmp_path / "tokens.db"))
    TokenCache().clear()
    SKeyCache().clear()

    db_manager = DatabaseManager(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'tokens.db'}"
    )
    await db_manager.initialize_models()

    manager = TokenManager(SimpleNamespace(db_manager=db_manager))
    yield manager

    TokenCache().clear()
    SKeyCache().clear()
    await db_manager.cleanup()


@pytest.mark.asyncio
async def test_revoked_token_fails_verification_immediately(token_manager):
    token = await token_manager.create_token(device_id="revocation-test")

    result = await token_manager.verify_token(token)
    assert result.is_valid

    # verify_token above populated the cache; revocation must still take
    # effect on the very next verification.
    revocation = await token_manager.revoke_token(token)
    assert revocation["status"] == "success"

    result = await token_manager.verify_token(token)
    assert not result.is_valid


@pytest.mark.asyncio
async def test_revoked_token_fails_verification_from_cold_cache(token_manager):
    token = await token_manager.create_token(device_id="revocation-cold-cache")
    await token_manager.revoke_token(token)
    TokenCache().clear()

    result = await token_manager.verify_token(token)
    assert not result.is_valid
    assert result.error == "Token revoked"


@pytest.mark.asyncio
async def test_revoking_twice_reports_already_revoked(token_manager):
    token = await token_manager.create_token(device_id="revocation-repeat")
    await token_manager.revoke_token(token)

    second = await token_manager.revoke_token(token)
    assert second["status"] == "info"


# --- Boot-bound, monotonic token lifetime ---------------------------------
#
# The device has no RTC, so wall-clock exp is advisory. Lifetime enforcement:
# within a boot its age is measured on CLOCK_BOOTTIME. In boot_bound mode a
# token also dies with the boot it was issued in; wall_clock_grace (the default)
# keeps previous-boot tokens valid until wall-clock expiry (7 days by default).


@pytest.fixture
def boot_bound_mode(monkeypatch):
    monkeypatch.setattr(
        token_module.settings, "TOKEN_LIFETIME_MODE", "boot_bound"
    )


@pytest.mark.asyncio
async def test_token_from_previous_boot_is_rejected(
    token_manager, monkeypatch, boot_bound_mode
):
    token = await token_manager.create_token(device_id="boot-bound")
    assert (await token_manager.verify_token(token)).is_valid

    monkeypatch.setattr(token_module, "current_boot_id", lambda: "new-boot-id")

    result = await token_manager.verify_token(token)
    assert not result.is_valid
    assert result.error == "Token from previous boot"


@pytest.mark.asyncio
async def test_monotonic_expiry_rejects_on_cache_hit_and_cold_path(
    token_manager, monkeypatch
):
    token = await token_manager.create_token(
        device_id="monotonic-expiry", expires_delta=timedelta(seconds=60)
    )
    assert (await token_manager.verify_token(token)).is_valid

    real_uptime = token_module.current_uptime()
    monkeypatch.setattr(
        token_module, "current_uptime", lambda: real_uptime + 61
    )

    # Cache is populated from the verify above: the fast path must reject too.
    result = await token_manager.verify_token(token)
    assert not result.is_valid
    assert result.error == "Token expired"

    TokenCache().clear()
    result = await token_manager.verify_token(token)
    assert not result.is_valid
    assert result.error == "Token expired"


@pytest.mark.asyncio
async def test_wall_clock_reset_cannot_resurrect_expired_token(
    token_manager, monkeypatch, boot_bound_mode
):
    token = await token_manager.create_token(
        device_id="no-resurrection", expires_delta=timedelta(seconds=60)
    )

    real_uptime = token_module.current_uptime()
    monkeypatch.setattr(
        token_module, "current_uptime", lambda: real_uptime + 61
    )
    assert not (await token_manager.verify_token(token)).is_valid

    # A reboot resets uptime to near zero and the wall clock to a stale base.
    # The boot id changed, so the token must stay dead regardless of clocks.
    monkeypatch.setattr(token_module, "current_uptime", lambda: 1.0)
    monkeypatch.setattr(token_module, "current_boot_id", lambda: "post-reboot")

    result = await token_manager.verify_token(token)
    assert not result.is_valid


@pytest.mark.asyncio
async def test_previous_boot_tokens_are_swept(
    token_manager, monkeypatch, boot_bound_mode
):
    stale = await token_manager.create_token(device_id="sweep-stale")

    monkeypatch.setattr(token_module, "current_boot_id", lambda: "boot-2")
    fresh = await token_manager.create_token(device_id="sweep-fresh")

    removed = await token_manager.purge_previous_boot_tokens()
    assert removed == 1

    TokenCache().clear()
    assert not (await token_manager.verify_token(stale)).is_valid
    assert (await token_manager.verify_token(fresh)).is_valid


@pytest.mark.asyncio
async def test_service_restart_without_reboot_keeps_tokens(token_manager):
    token = await token_manager.create_token(device_id="restart-survivor")

    # Same boot id: a wlanpi-core restart must not invalidate anything.
    removed = await token_manager.purge_previous_boot_tokens()
    assert removed == 0
    assert (await token_manager.verify_token(token)).is_valid


# --- wall_clock_grace mode ------------------------------------------------
#
# Previous-boot tokens stay valid until wall-clock expiry. The wall clock is
# only trusted across reboots because setting it requires SSH/sudo — the same
# privilege that can mint tokens anyway. Within a boot both modes are
# monotonic, so time manipulation still cannot stretch a live token.


@pytest.fixture
def grace_mode(monkeypatch):
    monkeypatch.setattr(
        token_module.settings, "TOKEN_LIFETIME_MODE", "wall_clock_grace"
    )


def test_default_lifetime_mode_is_wall_clock_grace():
    assert token_module.settings.TOKEN_LIFETIME_MODE == "wall_clock_grace"
    assert token_module.settings.ACCESS_TOKEN_EXPIRE_DAYS == 7


@pytest.mark.asyncio
async def test_grace_mode_accepts_previous_boot_token_within_wall_expiry(
    token_manager, monkeypatch, grace_mode
):
    token = await token_manager.create_token(device_id="grace-survivor")

    monkeypatch.setattr(token_module, "current_boot_id", lambda: "post-reboot")
    monkeypatch.setattr(token_module, "current_uptime", lambda: 1.0)

    assert (await token_manager.verify_token(token)).is_valid

    removed = await token_manager.purge_previous_boot_tokens()
    assert removed == 0


@pytest.mark.asyncio
async def test_grace_mode_rejects_wall_expired_previous_boot_token(
    token_manager, monkeypatch, grace_mode
):
    token = await token_manager.create_token(
        device_id="grace-expired", expires_delta=timedelta(seconds=-60)
    )

    monkeypatch.setattr(token_module, "current_boot_id", lambda: "post-reboot")

    result = await token_manager.verify_token(token)
    assert not result.is_valid
    assert result.error == "Token expired"


@pytest.mark.asyncio
async def test_grace_mode_rejects_retryably_while_clock_lags_issuance(
    token_manager, monkeypatch, grace_mode
):
    token = await token_manager.create_token(device_id="grace-clock-lag")

    monkeypatch.setattr(token_module, "current_boot_id", lambda: "post-reboot")

    real_datetime = token_module.datetime

    class StaleClock:
        @staticmethod
        def now(tz=None):
            return real_datetime.fromtimestamp(1000.0, tz=tz)

        @staticmethod
        def fromtimestamp(ts, tz=None):
            return real_datetime.fromtimestamp(ts, tz=tz)

    monkeypatch.setattr(token_module, "datetime", StaleClock)

    result = await token_manager.verify_token(token)
    assert not result.is_valid
    assert result.error == "Clock not yet synchronized"

    # Nothing was purged: once the clock catches up, the token works again.
    monkeypatch.setattr(token_module, "datetime", real_datetime)
    TokenCache().clear()
    assert (await token_manager.verify_token(token)).is_valid


@pytest.mark.asyncio
async def test_grace_mode_same_boot_still_monotonic_despite_clock_jump(
    token_manager, monkeypatch, grace_mode
):
    token = await token_manager.create_token(
        device_id="grace-monotonic", expires_delta=timedelta(seconds=60)
    )

    # Wall clock jumped far past exp, but this boot's monotonic age rules.
    real_datetime = token_module.datetime

    class FutureClock:
        @staticmethod
        def now(tz=None):
            return real_datetime.now(tz) + timedelta(days=30)

        @staticmethod
        def fromtimestamp(ts, tz=None):
            return real_datetime.fromtimestamp(ts, tz=tz)

    monkeypatch.setattr(token_module, "datetime", FutureClock)

    assert (await token_manager.verify_token(token)).is_valid
