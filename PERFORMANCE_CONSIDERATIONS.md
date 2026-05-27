# Performance considerations — review response

Response to PR review findings on `list_configs()` sync I/O and `ConnectionMonitor` threading.

**Deployment context:** production runs gunicorn with **`--workers 1`** and a single UvicornWorker (`debian/wlanpi-core.service`). One asyncio event loop serves all HTTP traffic. Synchronous work inside `async def` handlers blocks every other request until it completes.

---

## Do (before / as part of merging this PR)

### 1. Treat event-loop blocking as the primary performance constraint

Do not add new synchronous subprocess or file I/O to `async def` API handlers without an explicit plan (executor, background job, or documented acceptance of blocking).

**Why today:** with one worker, a slow handler makes the whole API feel stuck — auth, health checks, UI polling, and config listing all queue behind it.

**Worst existing offenders (already in codebase, not introduced by this PR):**

| Endpoint / path | Blocking work |
|-----------------|---------------|
| `POST /network/config/activate/{id}` | Full `activate_config()`: netns prep, phy moves, wpa/dhcp setup, multi-adapter loop |
| `POST /network/config/deactivate/{id}` | Sequential deactivate + `revert_to_root` |
| `GET /network/config/status` | Multiple `sudo ip` / `sudo iw` subprocess calls per namespace |

These are the realistic causes of a sluggish device. Optimizing `list_configs()` before addressing these would mis-prioritize effort.

### 2. Preserve the non-blocking WPA activation path (regression guard)

Keep `ConnectionMonitor` **off the request path** for secured configs: `activate_config()` must return `provisioned` immediately after starting the monitor, without waiting for `wpa_state=COMPLETED`, DHCP, routes, or autostart apps.

**Why today:** this was an explicit design choice to avoid multi-second API hangs while SSIDs connect. The namespace test matrix covers delayed-connect and provisioned-persist scenarios (`ACTIVATION_OUTCOMES.md`).

**Do not regress to:** blocking activate on WPA connect, or moving monitor polling back into the activate handler.

### 3. Respond to the review with scoped acceptance

Post a clear PR reply: accept the findings as valid **future** concerns; defer implementation unless we measure a problem. This PR’s namespace/rollback work does not add new event-loop blocking beyond existing sync-in-async patterns.

### 4. One cheap hygiene fix when touching `list_configs()` next

Read `current.txt` **once** before the config loop (today it is re-read per file). Low risk, no behaviour change, removes unnecessary I/O. Not urgent at current config counts, but do it in the next edit to that function rather than adding a cache layer prematurely.

---

## Don't

- **Don't replace `ConnectionMonitor` threads with `asyncio.Task` in this PR.** `get_wpa_status()`, DHCP restart, and route setup are synchronous subprocess paths. Async tasks would still need `asyncio.to_thread()` / an executor unless those utilities are rewritten. No user-visible gain; high churn and test risk.

- **Don't add a list_configs cache yet.** Validation-at-list-time is intentional (malformed configs appear as `"name (malformed)"` / `"name (empty)"`). Caching adds invalidation complexity for a path that is not a measured bottleneck.

- **Don't increase gunicorn workers as a quick fix.** Network namespace state, wpa_supplicant, and config activation are process-global; multiple workers without shared state would cause correctness bugs, not just perf wins.

---

## Defer (track, don't block merge)

| Item | Rationale |
|------|-----------|
| Lazy validation on `GET /network/config/` | Only parse full JSON on `GET /{id}` or on write; list returns ids + active flag + optional mtime |
| `run_in_executor` / async subprocess for activate, deactivate, status | Right fix for single-worker blocking; needs design + incremental rollout |
| Config list caching (mtime-based) | Worth it only if saved config count or list latency becomes measurable |
| Async-native monitor lifecycle | Tie background work to app lifespan/shutdown; refactor when subprocess layer is async-capable |

---

## Strategic change (future architecture)

1. **Separate “fast API” from “slow network operations.”** Long-running work (activate, deactivate, full status sweep) should run in a background job or executor and expose progress/status via polling or events — not hold the HTTP request open on the single event loop.

2. **Unify background work under one model.** Replace ad hoc daemon threads with tasks/jobs registered at startup, cancelled at shutdown, with explicit ownership per interface/namespace key (same as today’s `monitor_key`, but lifecycle-aware).

3. **Measure before optimizing list.** If list latency matters, profile with realistic config counts on target hardware; optimize validation depth before adding caches.

---

## Summary for reviewers

- **`list_configs()`:** valid future concern; low impact at expected scale; intentional validation behaviour.
- **`ConnectionMonitor` threads:** appropriate for off-loop polling of sync subprocess code; not a source of API-wide blocking today.
- **Real risk to responsiveness:** synchronous activate / deactivate / status on a **single-worker** asyncio app — existing debt, not a regression from this PR.
