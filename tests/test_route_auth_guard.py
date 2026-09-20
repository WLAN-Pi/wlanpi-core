"""Guard rail: every API route is authenticated or on the public allowlist.

New routes must either declare an auth dependency or be added to PUBLIC_ROUTES
with a review. Non-APIRoute routes are out of scope: ``/docs`` and the OpenAPI
JSON are framework-owned, ``/static`` is a mount, and the capture WebSocket
authenticates in-band (see ``tests/test_capture_ws_auth.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi.routing import APIRoute

from wlanpi_core.app import create_app
from wlanpi_core.core.auth import verify_auth_wrapper, verify_hmac, verify_jwt_token

try:
    # FastAPI >= 0.141 wraps included routers lazily, so app.routes no longer
    # holds APIRoutes directly. iter_route_contexts resolves them and keeps the
    # prefixed path. Older FastAPI resolves eagerly and has no such helper.
    from fastapi.routing import iter_route_contexts as _iter_route_contexts
except ImportError:  # pragma: no cover - only on older FastAPI
    _iter_route_contexts: Any = None  # type: ignore[no-redef]

AUTH_DEPENDENCIES = {verify_auth_wrapper, verify_hmac, verify_jwt_token}

# Public HTML and redirect views. Intentionally reachable without a token.
PUBLIC_ROUTES = frozenset({"/", "/api", "/api/v1", "/favicon.ico"})


def _api_routes() -> Iterator[tuple[str, APIRoute]]:
    """Yield (full path, APIRoute) for every route in the application."""
    app = create_app(debug=False)
    if _iter_route_contexts is None:
        for route in app.routes:
            if isinstance(route, APIRoute):
                yield route.path, route
        return
    for context in _iter_route_contexts(app.routes):
        if context.path is not None and isinstance(context.original_route, APIRoute):
            yield context.path, context.original_route


def _has_auth(route: APIRoute) -> bool:
    # ponytail: top-level auth deps only; recurse if a route ever nests auth.
    return any(dep.call in AUTH_DEPENDENCIES for dep in route.dependant.dependencies)


def _routes() -> list[tuple[str, APIRoute]]:
    return list(_api_routes())


def test_walker_sees_all_routes():
    # Fails loudly if a FastAPI change stops the walk from descending into
    # included routers, which would make the guard below pass vacuously.
    assert len(_routes()) >= 50


def test_every_api_route_is_authenticated():
    unauthenticated = sorted(
        path
        for path, route in _routes()
        if path not in PUBLIC_ROUTES and not _has_auth(route)
    )

    assert not unauthenticated, f"routes missing authentication: {unauthenticated}"


def test_public_allowlist_has_no_stale_entries():
    paths = {path for path, _ in _routes()}

    assert PUBLIC_ROUTES <= paths, f"stale allowlist entries: {PUBLIC_ROUTES - paths}"


def test_guard_distinguishes_public_and_protected():
    routes = _routes()

    assert any(_has_auth(route) for _, route in routes)
    assert _has_auth(next(route for path, route in routes if path == "/")) is False
