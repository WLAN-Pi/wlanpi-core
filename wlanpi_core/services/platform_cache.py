"""Process-wide cache of one `wlanpi-model -b` probe."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass

from wlanpi_core.core.transmit_policy import (
    TRANSMIT_ALLOWED_MODELS,
    is_go_token,
)

_UNKNOWN = "Unknown"
_lock = threading.Lock()


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


def _probe_unlocked(prior: PlatformSnapshot | None) -> PlatformSnapshot:
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


def store_platform_snapshot(snapshot: PlatformSnapshot) -> PlatformSnapshot:
    """Overwrite the process slot."""
    global _cached
    _cached = snapshot
    return snapshot


def clear_platform_cache() -> None:
    """Drop the slot so the next read is cold."""
    global _cached
    _cached = None


def load_platform_cache() -> PlatformSnapshot:
    """Probe `get_platform()` once and store the snapshot."""
    with _lock:
        if _cached is not None:
            return _cached
        return _probe_unlocked(None)


def resolve_model() -> ModelToken:
    """Return a final token, probing again when the stored one is not final.

    `Go`, `M4+`, `R4`, `R5`, and `Pro` stick. The first `M4` does not, because
    `wlanpi-model -b` prints `M4` when Go detection fails. A second `M4`
    sticks. A timeout or any other string is probed again on the next call.
    """
    # ponytail: one lock, and a non-final model re-probes on every gated call.
    # Add a backoff if that probe shows up under load.
    with _lock:
        if _cached is not None and _cached.final:
            return token_from_snapshot(_cached)
        prior = _cached
        stored = _probe_unlocked(prior)
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
