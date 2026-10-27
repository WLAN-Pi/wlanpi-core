"""Process-wide cache of the `wlanpi-model -b` result."""

from __future__ import annotations

import subprocess
import threading

from wlanpi_core.core.transmit_policy import TRANSMIT_ALLOWED_MODELS, is_go_token

_UNKNOWN = "Unknown"
_lock = threading.Lock()
_cached: str | subprocess.TimeoutExpired | None = None
_probe_generation = 0


def _probe() -> None:
    from wlanpi_core.services.system_service import get_platform

    global _cached, _probe_generation
    try:
        _cached = get_platform()
    except subprocess.TimeoutExpired as exc:
        _cached = exc
    _probe_generation += 1


def _token() -> str:
    if not isinstance(_cached, str) or _cached == "" or _cached.endswith("?"):
        return _UNKNOWN
    return _cached


def _is_final() -> bool:
    # `wlanpi-model -b` falls back to `M4` when it misses a Go, so `M4` is
    # probed again on every gated call.
    model = _token()
    return is_go_token(model) or (model in TRANSMIT_ALLOWED_MODELS and model != "M4")


def load_platform_cache() -> None:
    """Probe once."""
    if _cached is not None:
        return
    with _lock:
        if _cached is None:
            _probe()


def cached_model() -> str:
    """Return the cached model, probing only when nothing has been loaded."""
    load_platform_cache()
    return _token()


def resolve_model() -> str:
    """Return the model, probing again unless the cached one is final."""
    generation_on_entry = _probe_generation
    with _lock:
        if not _is_final() and _probe_generation == generation_on_entry:
            _probe()
        return _token()


def boot_model() -> str:
    """Return the raw probe string, re-raising a probe timeout."""
    load_platform_cache()
    if isinstance(_cached, subprocess.TimeoutExpired):
        raise _cached
    return _cached or ""
