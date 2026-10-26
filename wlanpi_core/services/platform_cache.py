"""Process-wide cache of one `wlanpi-model -b` probe."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass

from wlanpi_core.constants import COMMAND_TIMEOUT_SEC
from wlanpi_core.core.transmit_policy import (
    TRANSMIT_ALLOWED_MODELS,
    is_go_token,
)

_UNKNOWN = "Unknown"
_PROBE_BACKOFF_SEC = float(COMMAND_TIMEOUT_SEC)
_lock = threading.Lock()
_inflight = False
_last_resolve_probe_at: float | None = None


@dataclass(frozen=True, slots=True)
class PlatformSnapshot:
    """One `get_platform()` result, or a planted test value."""

    model: str
    error: subprocess.TimeoutExpired | None = None
    final: bool = True
    m4_confirmations: int = 0


@dataclass(frozen=True, slots=True)
class ModelToken:
    """Model name the gate may see. A blank or `?` suffix cannot be constructed."""

    value: str

    def __post_init__(self) -> None:
        """Reject a blank probe and a `?` suffix."""
        if self.value == "" or self.value.endswith("?"):
            raise ValueError(
                "model token must be a non-empty string that does not end with ?"
            )


_cached: PlatformSnapshot | None = None


def token_from_snapshot(snapshot: PlatformSnapshot) -> ModelToken:
    """Fold a timeout, blank stdout, or a `?` suffix to `Unknown`."""
    if (
        snapshot.error is not None
        or snapshot.model == ""
        or snapshot.model.endswith("?")
    ):
        return ModelToken(_UNKNOWN)
    return ModelToken(snapshot.model)


def _is_final(
    model: str, error: subprocess.TimeoutExpired | None, m4_count: int
) -> bool:
    if error is not None or model == "" or model.endswith("?"):
        return False
    if is_go_token(model):
        return True
    if model in TRANSMIT_ALLOWED_MODELS and model != "M4":
        return True
    return model == "M4" and m4_count >= 2


def _snapshot_for_probe(
    model: str,
    error: subprocess.TimeoutExpired | None,
    prior: PlatformSnapshot | None,
) -> PlatformSnapshot:
    m4_count = 0
    if prior is not None and prior.error is None and prior.model == "M4":
        m4_count = prior.m4_confirmations
    if error is None and model == "M4":
        m4_count += 1
    return PlatformSnapshot(
        model="" if error is not None else model,
        error=error,
        final=_is_final("" if error is not None else model, error, m4_count),
        m4_confirmations=m4_count,
    )


def _probe(prior: PlatformSnapshot | None) -> PlatformSnapshot:
    from wlanpi_core.services.system_service import get_platform

    try:
        model = get_platform()
    except subprocess.TimeoutExpired as exc:
        return store_platform_snapshot(_snapshot_for_probe("", exc, prior))
    return store_platform_snapshot(_snapshot_for_probe(model, None, prior))


def cached_model() -> ModelToken:
    """Return the startup token. A cold cache is `Unknown` and does not probe."""
    if _cached is None:
        return ModelToken(_UNKNOWN)
    return token_from_snapshot(_cached)


def _is_provisional_m4(snapshot: PlatformSnapshot) -> bool:
    return snapshot.error is None and snapshot.model == "M4" and not snapshot.final


def _resolve_should_wait(snapshot: PlatformSnapshot) -> bool:
    if _is_provisional_m4(snapshot):
        return False
    if _last_resolve_probe_at is None:
        return False
    return (time.monotonic() - _last_resolve_probe_at) < _PROBE_BACKOFF_SEC


def _end_inflight(*, count_as_resolve: bool) -> None:
    global _inflight, _last_resolve_probe_at
    with _lock:
        _inflight = False
        if count_as_resolve:
            _last_resolve_probe_at = time.monotonic()


def store_platform_snapshot(snapshot: PlatformSnapshot) -> PlatformSnapshot:
    """Overwrite the process slot."""
    global _cached
    with _lock:
        _cached = snapshot
        return snapshot


def clear_platform_cache() -> None:
    """Drop the slot so the next read is cold."""
    global _cached, _inflight, _last_resolve_probe_at
    with _lock:
        _cached = None
        _inflight = False
        _last_resolve_probe_at = None


def load_platform_cache() -> PlatformSnapshot:
    """Probe `get_platform()` once and store the snapshot."""
    global _inflight
    with _lock:
        if _cached is not None:
            return _cached
        _inflight = True
    try:
        return _probe(None)
    finally:
        _end_inflight(count_as_resolve=False)


def resolve_model() -> ModelToken:
    """Return a final token, probing when the stored one is not final.

    One `M4` is probed again before this call returns. A non-final result
    other than that first `M4` waits out the backoff before the next probe.
    """
    # ponytail: one probe in flight. Other gated calls fail closed and do not
    # wait on it. A non-final result other than a first M4 waits
    # _PROBE_BACKOFF_SEC (one command timeout) before another probe. A first
    # M4 is confirmed in this call. If a probe still ties up a worker, run it
    # on its own thread.
    global _inflight
    with _lock:
        if _cached is not None and _cached.final:
            return token_from_snapshot(_cached)
        if _inflight:
            return ModelToken(_UNKNOWN)
        if _cached is not None and _resolve_should_wait(_cached):
            return ModelToken(_UNKNOWN)
        _inflight = True
        prior = _cached
    try:
        stored = _probe(prior)
        if _is_provisional_m4(stored):
            stored = _probe(stored)
    finally:
        _end_inflight(count_as_resolve=True)
    if not stored.final:
        return ModelToken(_UNKNOWN)
    return token_from_snapshot(stored)


def boot_model() -> str:
    """Return the raw probe string for non-default profile restore.

    Re-raise `snapshot.error` so a stored timeout still skips activation.
    Raise `RuntimeError` when the slot is cold so a skipped `load` cannot
    look like a successful `"Unknown"` probe.
    """
    if _cached is None:
        raise RuntimeError("platform model was not loaded at startup")
    if _cached.error is not None:
        raise _cached.error
    return _cached.model
