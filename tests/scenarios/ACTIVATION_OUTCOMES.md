# activate_config outcome model

Reference for matrix authors and reviewers. Implementation: `wlanpi_core/utils/network_config.py`.

## Three paths (do not conflate them)

| Path | Trigger | Rollback? | current.txt | Typical matrix scope |
|------|---------|-----------|-------------|----------------------|
| **1. Persist** | Loop completes; every outcome is `connected` or `provisioned` | No | Written to cfg_id | `positive`, `hw-absence`, `delayed-connect` |
| **2. Return False** | Loop completes; any outcome is `error` | Yes (`activated_configs`) | Unchanged | `hw-fault` (e.g. phy move → status error) |
| **3. Exception** | `ns.activate_config()` raises mid-loop | Yes (`activated_configs`), then re-raise | Unchanged | `hw-fault` (e.g. bring_interface_up raises) |

## Tolerated partial success (path 1 — NOT rollback)

These return **`provisioned`** (or `connected`), not `error`, so activation **persists**:

- Missing / unplugged interface (`discovery` skip) — `hw-absence`
- Delayed SSID at activate time — `delayed-connect` / `ssid_prestage_*`
- WPA still connecting via `ConnectionMonitor` after activate returns

**Do not** expect rollback for these. They are intentional product behaviour.

## UNACCEPTABLE failure (paths 2 and 3 — rollback)

- Interface present but prepare fails → **`status=error`** (path 2)
- Same class of fault but **`RunCommandError` raised** instead of error status (path 3)

Both must roll back entries already applied and leave `current.txt` unchanged.

## current.txt helpers

| Function | Mutates current.txt? | Use |
|----------|----------------------|-----|
| `get_current_config()` | No (read-only) | Validation, `is_active`, activate pre-check |
| `recover_current_config()` | Yes → `default` on malformed | App startup, recovery tests |

## Matrix tests

- `partial_activation_rollback` — path 2
- `activation_exception_mid_loop_rollback` — path 3
- `multi_adapter_one_unplugged_*` — path 1 (contrast with hw-fault)
- `ssid_prestage_immediate_provisioned` — path 1 (provisioned is success)
