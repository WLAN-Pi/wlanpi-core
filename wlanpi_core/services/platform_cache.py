"""Process-wide cache of one `wlanpi-model -b` probe."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

_UNKNOWN = "Unknown"


@dataclass(frozen=True, slots=True)
class PlatformSnapshot:
    """One `get_platform()` result, or a planted test value."""

    model: str
    error: subprocess.TimeoutExpired | None


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
    """Fold a timeout, blank stdout, a `?` suffix, or `Unknown` to `Unknown`."""
    if (
        snapshot.error is not None
        or snapshot.model == ""
        or snapshot.model.endswith("?")
        or snapshot.model == _UNKNOWN
    ):
        return ModelToken(_UNKNOWN)
    return ModelToken(snapshot.model)


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
    """Probe `get_platform()` once per process and store the snapshot."""
    if _cached is not None:
        return _cached
    from wlanpi_core.services.system_service import get_platform

    try:
        model = get_platform()
    except subprocess.TimeoutExpired as exc:
        return store_platform_snapshot(PlatformSnapshot(model="", error=exc))
    return store_platform_snapshot(PlatformSnapshot(model=model, error=None))


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
