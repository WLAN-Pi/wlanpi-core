"""Transmit gate: one table, one dependency, startup platform cache."""

from collections.abc import Callable

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute, iter_route_contexts
from starlette.requests import HTTPConnection

from wlanpi_core.api.api_v1.api import api_router
from wlanpi_core.api.openapi_docs import (
    RESPONSES_TRANSMIT_FORBIDDEN,
    TRANSMIT_DISABLED_ON_GO,
    TRANSMIT_DISABLED_UNKNOWN,
)
from wlanpi_core.services.system_service import get_model

TransmitPredicate = Callable[[HTTPConnection], bool]

TRANSMIT_SERVICE_NAMES: frozenset[str] = frozenset(
    {
        "hostapd",
        "wlanpi-profiler",
        "wpa_supplicant",
        "wpa_supplicant@wlan0",
        "kismet",
        "wlanpi-grafana-scanner-wlan0",
        "wlanpi-grafana-scanner-wlan1",
        "wlanpi-grafana-scanner-wlan2",
        "bt-agent",
        "bt-network",
    }
)

_REFUSED_MODELS: frozenset[str] = frozenset({"Go", "Unknown", "Unknown platform", ""})

_MountedRoute = tuple[str, str | None, APIRoute]


def _always(_connection: HTTPConnection) -> bool:
    """Return True for an operation that always transmits."""
    return True


def _power_on(connection: HTTPConnection) -> bool:
    """Return True when the Bluetooth `action` path parameter is `on`."""
    return connection.path_params.get("action") == "on"


def _transmit_service(connection: HTTPConnection) -> bool:
    """Return True when the `name` query is a transmit systemd unit."""
    name = connection.query_params.get("name")
    if name is None:
        return False
    canonical = name.strip().lower().replace(".service", "")
    return canonical in TRANSMIT_SERVICE_NAMES


def _detail(model: str) -> str:
    """Return the 403 detail for a refused model."""
    if model == "Go":
        return TRANSMIT_DISABLED_ON_GO
    return TRANSMIT_DISABLED_UNKNOWN


GATED_OPERATIONS: dict[tuple[str, str], TransmitPredicate] = {
    ("POST", "/api/v1/profiler/start"): _always,
    ("POST", "/api/v1/network/config/activate/{id}"): _always,
    ("POST", "/api/v1/system/reg-domain/set"): _always,
    ("POST", "/api/v1/bluetooth/pair"): _always,
    ("GET", "/api/v1/utils/wlan/scan"): _always,
    ("GET", "/api/v1/network/wlan/scan"): _always,
    ("POST", "/api/v1/bluetooth/power/{action}"): _power_on,
    ("POST", "/api/v1/system/service/start"): _transmit_service,
    ("POST", "/api/v1/system/service/restart"): _transmit_service,
}


def _mounted_api_routes(app: FastAPI) -> list[_MountedRoute]:
    """Return each mounted API route path, path format, and route."""
    mounted: list[_MountedRoute] = []
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute) or context.path is None:
            continue
        mounted.append((context.path, context.path_format, route))
    return mounted


def _routes_for_key(
    mounted: list[_MountedRoute], method: str, template: str
) -> list[APIRoute]:
    """Return the one API route mounted at `method` and `template`."""
    found: list[APIRoute] = []
    for path, path_format, route in mounted:
        methods = route.methods
        if methods is None or path != template or method not in methods:
            continue
        if path_format != path:
            raise RuntimeError(
                f"transmit gate key {(method, template)!r} has path_format {path_format!r}"
            )
        found.append(route)
    if len(found) != 1:
        raise RuntimeError(
            f"transmit gate key {(method, template)!r} matched {len(found)} routes"
        )
    return found


def _route_index(mounted: list[_MountedRoute]) -> dict[int, str]:
    """Map each mounted API route object to its mounted path template."""
    index: dict[int, str] = {}
    for path, _path_format, route in mounted:
        previous = index.get(id(route))
        if previous is not None and previous != path:
            raise RuntimeError(
                f"transmit gate index has APIRoute {route.name} at {previous} and {path}"
            )
        index[id(route)] = path
    return index


async def enforce_transmit_gate(connection: HTTPConnection) -> None:
    """Refuse gated transmit operations on a Go or an unknown model.

    Registered once, on the v1 `include_router`. A route that is not in
    `GATED_OPERATIONS` returns without raising. A matching predicate that
    returns false returns without raising.
    """
    route = connection.scope.get("route")
    if not isinstance(route, APIRoute):
        return
    method = connection.scope.get("method")
    if not isinstance(method, str):
        return
    if method == "HEAD":
        method = "GET"
    app = connection.scope["app"]
    templates = getattr(app.state, "transmit_route_templates", None)
    if not isinstance(templates, dict):
        raise RuntimeError("transmit gate index was not installed")
    template = templates.get(id(route))
    if not isinstance(template, str):
        raise RuntimeError(f"transmit gate index is missing APIRoute {route.path}")
    predicate = GATED_OPERATIONS.get((method, template))
    if predicate is None or not predicate(connection):
        return
    model = get_model()
    if model not in _REFUSED_MODELS:
        return
    raise HTTPException(status_code=403, detail=_detail(model))


def install_transmit_gate(app: FastAPI) -> None:
    """Index mounted templates and stamp 403 onto each gated operation.

    Call once from `create_app` after `include_router`. Raises
    `RuntimeError` when a table row is not mounted exactly once.
    """
    mounted = _mounted_api_routes(app)
    for method, template in GATED_OPERATIONS:
        route = _routes_for_key(mounted, method, template)[0]
        updated = dict(route.responses)
        updated.update(RESPONSES_TRANSMIT_FORBIDDEN)
        route.responses = updated
    api_router._mark_routes_changed()
    app.state.transmit_route_templates = _route_index(_mounted_api_routes(app))
