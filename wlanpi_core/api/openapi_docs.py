"""
OpenAPI metadata, tag descriptions, and shared response definitions.

Used by FastAPI ``openapi_tags``, route ``responses=``, and the integration guide.
"""
from __future__ import annotations

from typing import Union

from wlanpi_core.schemas.common.errors import (
    ApiErrorResponse,
    DeprecatedEndpointResponse,
    MessageResponse,
    ScanInProgressResponse,
    ScanNeedsSelectionResponse,
    ScanNoAdapterResponse,
)

OPENAPI_DESCRIPTION = """
# wlanpi-core REST API

HTTP API for WLAN Pi device control, network configuration, Wi-Fi primitives, and utilities.

**Base path:** `/api/v1`  
**Interactive docs:** `/docs` (this page) · **OpenAPI JSON:** `/api/v1/openapi.json`

## Authentication

| Caller | Header | How to obtain |
|--------|--------|----------------|
| Remote apps (mobile, WebUI) | `Authorization: Bearer <jwt>` | On-device: `POST /api/v1/auth/token` via **localhost HMAC** (see authentication tag). Remote callers cannot bootstrap JWT without device-local pairing. |
| On-device services (wlanpi-ui) | `X-Request-Signature: …` | HMAC with shared secret |

JWT default lifetime: **7 days**. All documented routes require auth unless noted.

## Conventions

- **JSON keys** are camelCase on the wire where Pydantic aliases are defined (e.g. `selectedAdapter`, `downloadSpeed`).
- **Device mode** (`classic`, `hotspot`, `wiperf`, …) is read from `/etc/wlanpi-state`. Some routes return **409** when the wrong mode is active.
- **Namespace configs** activate only in **classic** mode. See `network_config` tag and the integration guide.
- **Deprecated** routes are grouped under the **`deprecated`** OpenAPI tag (legacy `/network/wlan/*`). Canonical replacements are listed per operation.
- **WLAN scan:** `GET /utils/wlan/scan` is canonical. `GET /network/wlan/scan` is deprecated and returns a legacy `nets[]` shape.

## Long-running and multi-step work

| Pattern | Examples | Client approach |
|---------|----------|-----------------|
| Single slow HTTP call | `GET /utils/speedtest` (30–90s) | Use generous timeout; poll is not required |
| Provision then poll | `POST /network/config/activate/{id}` | Returns `provisioned` immediately; poll `GET /network/config/status` for SSID |
| WebSocket stream | `WS /streaming/capture` | JSON command protocol; see streaming tag |
| Mode-gated read | Hotspot clients, stations | Expect **409** outside hotspot mode |

**Workflow guide:** see `docs/API-INTEGRATION-GUIDE.md` in the repository (progressive worked examples for app and MCP authors).

## Related deep-dive docs

| Topic | Document |
|-------|----------|
| WLAN scan | `docs/P0-utils-wlan-scan-api.md` |
| Speedtest / reachability | `docs/P0-utils-reachability-speedtest-api.md` |
| WLAN USB/PCI drivers | `docs/P0-network-wlan-drivers-api.md` |
| Date/time | `docs/P0-system-datetime-api.md` |
| Reg domain | `docs/P0-system-reg-domain-api.md` |
| Deprecated routes | `docs/API-DEPRECATED-ENDPOINTS.md` |
"""

OPENAPI_TAGS: list[dict[str, str]] = [
    {
        "name": "authentication",
        "description": (
            "JWT issuance and revocation. Remote clients authenticate once, "
            "then send `Authorization: Bearer` on every request."
        ),
    },
    {
        "name": "system",
        "description": (
            "Device identity, stats, battery, date/time, regulatory domain, "
            "service control (systemd), power actions, and **hotspot-only** "
            "reads (`/system/hotspot/*` require device mode `hotspot`)."
        ),
    },
    {
        "name": "network",
        "description": (
            "Interface listing, VLANs, routing, sockets, DHCP, link stats, "
            "and WLAN driver discovery."
        ),
    },
    {
        "name": "deprecated",
        "description": (
            "Legacy `/network/wlan/*` paths kept for backward compatibility. "
            "Each operation documents its replacement. Prefer `network_config` "
            "and `device utils` WLAN scan for new development."
        ),
    },
    {
        "name": "network_config",
        "description": (
            "NetConfig CRUD and activate/deactivate (classic mode). Activation "
            "is asynchronous — poll `/network/config/status` for connection state."
        ),
    },
    {
        "name": "network_information",
        "description": "Aggregated network document (LLDP, CDP, public IP, interface summaries).",
    },
    {
        "name": "wifi",
        "description": (
            "Wi-Fi PHY capabilities, regulatory domain, and **hotspot-only** "
            "station/link stats (`409` when not in hotspot mode)."
        ),
    },
    {
        "name": "device utils",
        "description": (
            "Reachability, speedtest (slow), WLAN scan, USB list, UFW, port blinker."
        ),
    },
    {
        "name": "bluetooth",
        "description": "Adapter status, power, and pairing (starts `bt-timedpair`).",
    },
    {
        "name": "profiler",
        "description": "WLAN Pi profiler start/stop/status.",
    },
    {
        "name": "streaming",
        "description": (
            "**WebSocket only** — no REST HTTP routes in this API version. "
            "Connect to `WS /api/v1/streaming/capture` (JSON command protocol; "
            "binary pcapng frames). Listed in OpenAPI for discoverability. "
            "REST capture session API is planned separately."
        ),
    },
]

# Shared OpenAPI response entries for route decorators: responses={**RESPONSES.auth, ...}
RESPONSES_AUTH = {
    401: {
        "model": MessageResponse,
        "description": "Missing or invalid Bearer token / HMAC signature",
    },
}

RESPONSES_MODE_CONFLICT = {
    409: {
        "model": MessageResponse,
        "description": "Device mode precondition not met (e.g. not in hotspot mode)",
    },
}

RESPONSES_GONE = {
    410: {
        "model": DeprecatedEndpointResponse,
        "description": "Endpoint removed — use the `replacement` path in the body",
    },
}

RESPONSES_SCAN = {
    409: {
        "model": Union[ScanNeedsSelectionResponse, ScanInProgressResponse],
        "description": (
            "Conflict — branch on JSON `error`: "
            "`NEEDS_SELECTION` (multiple monitors; pass `iface`/`namespace`) or "
            "`SCAN_IN_PROGRESS` (same adapter already scanning; coalesce/retry)."
        ),
    },
    422: {
        "model": ScanNoAdapterResponse,
        "description": "No suitable scan adapter available",
    },
}

RESPONSES_API_ERROR = {
    400: {
        "model": ApiErrorResponse,
        "description": "Invalid request (e.g. bad query parameters)",
    },
    503: {
        "model": ApiErrorResponse,
        "description": "Underlying command or dependency unavailable",
    },
}

RESPONSES_SERVICE_UNAVAILABLE = {
    503: {
        "model": MessageResponse,
        "description": "Underlying command or hardware unavailable",
    },
}
