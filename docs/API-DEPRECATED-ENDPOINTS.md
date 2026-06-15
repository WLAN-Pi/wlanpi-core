# Deprecated API endpoints

**OpenAPI:** deprecated routes show `deprecated: true` in `/api/v1/openapi.json` and strikethrough in `/docs`.

| Legacy path | Status | Replacement | Notes |
|-------------|--------|-------------|-------|
| `GET /network/wlan/scan` | **Redirected** | `GET /utils/wlan/scan` | Same auth; maps to legacy `nets[]` shape. Prefer canonical endpoint for new code. |
| `GET /network/wlan/getInterfaces` | **Redirected** | `GET /network/config/status` | Now uses `iw dev`, not DBus. |
| `GET /network/wlan/getConnected` | **Redirected** | `GET /network/config/status` | Uses `wpa_cli status`. |
| `POST /network/wlan/set-dbus` | **410 Gone** | `POST /network/config/` + `POST /network/config/activate/{id}` | Body includes `replacement` path. |
| `POST /network/wlan/set` | **410 Gone** | Same as set-dbus | Broken legacy stub removed. |
| `POST /network/wlan/revert` | **Live (align)** | `POST /network/config/deactivate/{id}` | Still works; prefer config deactivate. |

## Response shapes

### 410 Gone (removed endpoints)

```json
{
  "error": "ENDPOINT_DEPRECATED",
  "message": "Use POST /api/v1/network/config/ then POST /api/v1/network/config/activate/{id}",
  "replacement": "/api/v1/network/config/"
}
```

### Redirected scan — extra statuses

| HTTP | Body | Meaning |
|------|------|---------|
| 409 | `{ "error": "NEEDS_SELECTION", "candidates": [...] }` | Multiple monitor adapters |
| 422 | `{ "error": "NO_SCAN_ADAPTER", "candidates": [] }` | No scan-capable adapter |

## Client migration checklist

1. Replace all `GET /network/wlan/scan` with `GET /utils/wlan/scan` (response shape differs — see [P0-utils-wlan-scan-api.md](./P0-utils-wlan-scan-api.md)).
2. Replace connect/set flows with NetConfig CRUD + activate (see [API-INTEGRATION-GUIDE.md](./API-INTEGRATION-GUIDE.md) §5).
3. Remove calls to `set-dbus` / `set`; handle 410 if still present in old apps.
4. Use `/network/config/status` instead of `getInterfaces` / `getConnected`.
