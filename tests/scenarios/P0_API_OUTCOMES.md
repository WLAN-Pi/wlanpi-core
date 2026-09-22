# P0 API outcome model

Reference for `p0_api_test_matrix.csv` authors and reviewers. Complements
`ACTIVATION_OUTCOMES.md` (namespace config) with HTTP API semantics.

## Mocking policy (agreed)

| Layer | CI behaviour | On-device |
|-------|--------------|-----------|
| FastAPI routing, auth, Pydantic validation | **Real** | Real |
| Service orchestration logic | **Real** | Real |
| Adapter enumeration (`discovery`, `config/status` parse) | **Stub only** for 0 / 1 / 2+ monitor permutations | Real hardware |
| CLI/script wrappers (`wlanpi-timezone`, `speedtest`, etc.) | Stub `run_command` return fixtures | Real execution |
| Namespace PHY move, wpa_supplicant start | Use existing namespace matrix | Real |

**Rule:** Stub the minimum needed to simulate hardware adapter layout. Do not mock HTTP, JWT verification, or response shaping unless testing auth isolation in a dedicated unit test.

## Scan adapter selection (`GET /utils/wlan/scan`)

| Path | Trigger | HTTP | Response |
|------|---------|------|----------|
| **Auto single** | 1 monitor adapter in status | 200 | `selectedAdapter` set; `networks` populated; scan runs |
| **Needs selection** | 2+ monitor adapters, no `iface` param | 200 | `needsSelection: true`; `candidates` list; **no scan** |
| **Explicit** | `iface` + optional `namespace` provided | 200 | Uses named adapter; `selectedAdapter` matches |
| **Managed fallback** | 0 monitor, ≥1 managed in root | 200 | Falls back to managed adapter in root |
| **No adapter** | 0 monitor, 0 managed suitable | 422 | `NO_SCAN_ADAPTER` error |

## Mode switch (`POST /system/mode/switch`)

| Path | Precondition | HTTP | Behaviour |
|------|--------------|------|-----------|
| **OK** | No active namespace config | 200 | Mode switcher script invoked; audit log entry |
| **Conflict** | `current.txt` points to active config | 409 | Message explains active config; no mode change |
| **Force** | Active config + `force: true` | 200 | Deactivate all configs (audit log); then mode switch |

## Namespace config activate (classic mode gate)

| Path | Device mode | HTTP | Behaviour |
|------|-------------|------|-----------|
| **Activate OK** | `classic` | 200 | Existing namespace matrix outcomes apply |
| **Query OK** | Any mode | 200 | `GET /network/config/status` always works |
| **Activate skipped** | Non-classic at startup | N/A | App init skips namespace restore (existing behaviour) |

API activate in non-classic: endpoint remains callable; document expected behaviour per product decision (likely 409 or 503 with clear message). Matrix row `mode_non_classic_activate_rejected` captures this.

## Auth

| Path | Request | HTTP |
|------|---------|------|
| **JWT valid** | Bearer from `POST /auth/token` | 200 on protected route |
| **JWT missing** | No Authorization | 401 |
| **JWT expired** | Expired token | 401 |

Remote clients: login once, 7-day JWT, no refresh token in P0.

## DBus legacy path repurposing

Legacy `/network/wlan/*` routes must delegate to namespace/wpa_cli implementations.
Matrix rows verify **same response shape** as new paths where compatibility promised;
OpenAPI `deprecated: true` on legacy routes.
