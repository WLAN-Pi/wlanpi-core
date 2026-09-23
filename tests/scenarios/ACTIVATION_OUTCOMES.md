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

## Identity vs absence (do not conflate)

`hw-absence` is "iface not found by `discovery.find_interface()` in any netns" (USB unplugged, late boot).
That path skips prepare and returns `provisioned`.

Stale PHY is the opposite: the iface **exists**, but `cfg.phy` names the
wrong radio or none at all (e.g. live `wlan1→phy2` while `default.json` says
`phy1`). Rows:

- `stale_phy_iface_on_other_radio` / `stale_phy_namespace_wrong_radio` (#236)
- `prepare_missing_phy_after_delete` (#236): delete-then-skip leaves a radio with no netdev
- `iface_already_in_netns_at_activation` (#236): the iface sits in another netns
- `phy10_vs_phy1_substring` (#236): `phy1` must not match `phy10`
- `iface_display_name_differs` (#236): the live iface carries `iface_display_name`
- `rollback_after_partial_prepare` (#236): rollback of namespaced entries
- `phy_index_neq_iface_index`: control, non-parity indexes are fine when cfg matches live
- `default_created_when_missing` / `default_single_radio_no_500` (#202): default
  built from the live inventory, no WPA2 without a psk
- `create_profile_snapshots_mac` (#237, Jake pin)

These rows run under `live_adapter_inventory_mocks`, a stateful fake of `iw`
and `ip netns` in `tests/conftest.py`. Deletes, adds, and phy moves change the
fake's state, and a phy move takes its ifaces with it, as the kernel does.
Rows assert the exact `deleted` / `adds` / `phy_moves` sequences and the final
`live()` map, not only `activate_config is True`. Stale rows configure
`mode=monitor` over a managed live iface, so a prepare that does nothing
cannot pass.

Rows that replicate an open bug are listed in `KNOWN_BUGS` in
`tests/test_namespace_matrix/test_matrix.py` and run as `xfail(strict=True)`.
The fix for that bug must delete its entries; an unexpected pass fails the run.
