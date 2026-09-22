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

## PHY / interface identity (do not conflate with adapter-count rows)

`hw-absence` in the namespace matrix is "iface missing from discovery". Stale PHY is
the opposite: iface exists, stored `phy` exists, they are the wrong pair.

HTTP rows (service assertions live in the namespace matrix):

| Row | Issue | HTTP | Extra assertion |
|-----|-------|------|-----------------|
| `network_config_activate_stale_phy_mismatch` | #236 | 200 | must not `iw phy phy1 interface add wlan1` |
| `network_config_activate_default_single_radio` | #202 | 200 not 500 | single-radio `activate/default` |
| `network_config_create_snapshots_mac` | #237 / Jake | 200 | GET config includes live MAC |

They hard-fail until the production fix lands (same as every other matrix row).

## WLAN_MANAGEMENT and overnight system APIs (#238 / #241)

Josh shipped these outside the matrix (`test_wlan_management.py`,
`test_system_ntp.py`, `test_system_api_async.py`). The HTTP contracts now live
here. Pure Settings parse is the `wlan_management_settings_parse` unit row;
service-level NTP/health parsers may still keep focused unit tests.

| Row | Issue | HTTP | Assertion |
|-----|-------|------|-----------|
| `wlan_management_settings_parse` | #238 | n/a | default/manual/normalize/bogus→auto |
| `system_device_info_wlan_management` | #238 / webui #123 | 200 | `wlan_management` present and reflects settings |
| `wlan_management_manual_activate_409` | #238 | 409 | activate gated |
| `wlan_management_manual_deactivate_409` | #238 | 409 | deactivate gated |
| `wlan_management_manual_revert_409` | #238 | 409 | revert gated |
| `system_ntp_get` / `system_ntp_set` | webui #124 | 200 | GET/POST `/system/ntp` |
| `system_health` | #241 | 200 | health snapshot keys |
| `system_services_failed` | #241 | 200 | failed units list |
| `wlan_link` | #241 | 200 | `iw link` association |

## DBus legacy path repurposing

Legacy `/network/wlan/*` routes must delegate to namespace/wpa_cli implementations.
Matrix rows verify **same response shape** as new paths where compatibility promised;
OpenAPI `deprecated: true` on legacy routes.
