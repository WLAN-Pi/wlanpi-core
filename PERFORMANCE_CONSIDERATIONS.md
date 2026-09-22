# Performance considerations — review response

Response to PR review findings on `list_configs()` sync I/O and `ConnectionMonitor` threading.

**Deployment context:** production runs gunicorn with **`--workers 1`** and a single UvicornWorker (`debian/wlanpi-core.service`). One asyncio event loop serves all HTTP traffic. Synchronous work inside `async def` handlers blocks every other request until it completes.

---

## Immediate action plan (this PR)

Concrete code changes to prevent the API from feeling stuck during network operations. **No changes to `ConnectionMonitor` or rollback logic.**

### Required — `wlanpi_core/api/api_v1/endpoints/network_config_api.py`

Add `import asyncio` and wrap blocking `network_config` calls with `asyncio.to_thread()`. This moves subprocess/file work off the event loop while keeping existing sync implementations unchanged.

| Handler | Current (blocks loop) | Change to |
|---------|----------------------|-----------|
| `get_status()` | `network_config.status()` | `await asyncio.to_thread(network_config.status)` |
| `get_configs()` | `network_config.list_configs()` | `await asyncio.to_thread(network_config.list_configs)` |
| `activate_config()` | `network_config.activate_config(id, override_active)` | `await asyncio.to_thread(network_config.activate_config, id, override_active)` |
| `deactivate_config()` | `network_config.deactivate_config(...)` | `await asyncio.to_thread(network_config.deactivate_config, id, override_active if override_active else False)` |

**Example (activate):**

```python
success = await asyncio.to_thread(network_config.activate_config, id, override_active)
```

**Why these four:** they are the slowest paths (multi-subprocess activate/deactivate/status sweep). Listing is included because the review flagged it and the fix is one line.

**Not in scope for this PR:** `get_config_by_id`, `create_config`, `edit_config`, `delete_config` — fast single-file ops; can follow the same pattern later if desired.

**Tests:** existing unit/matrix tests call `network_config` directly and are unaffected. No new tests required; optional smoke test that API handlers remain async-safe.

### Recommended — `wlanpi_core/utils/network_config.py` (`list_configs`)

Read `current.txt` once before the config loop instead of per file:

```python
active_id = ccf.read_text().strip() if ccf.exists() else None
# inside loop:
is_active = active_id == cfg_stem
```

Low risk hygiene; pairs with the review feedback without adding a cache.

### Explicitly no change

| Area | Reason |
|------|--------|
| `ConnectionMonitor` / `_monitor_connection_async` | Already off the request path; threads are appropriate for sync subprocess polling |
| `activate_config()` / `NetworkNamespaceService` internals | Behaviour correct; only the API wrapper needs `to_thread` |
| gunicorn worker count | Must stay at 1 for process-global netns/wpa state |
| list validation / caching | Intentional malformed annotations; defer cache until measured |

---

## Do (before / as part of merging this PR)

### 1. Treat event-loop blocking as the primary performance constraint

Do not add new synchronous subprocess or file I/O to `async def` API handlers without `asyncio.to_thread()` or a background job.

**Why today:** with one worker, a slow handler makes the whole API feel stuck — auth, health checks, UI polling, and config listing all queue behind it.

### 2. Apply the immediate action plan above

Offload **activate, deactivate, status, and list** in `network_config_api.py`. This is the minimum code change that addresses the review without refactoring subprocess utilities.

### 3. Preserve the non-blocking WPA activation path (regression guard — no code change)

Keep `ConnectionMonitor` **off the request path** for secured configs: `activate_config()` must return `provisioned` immediately after starting the monitor, without waiting for `wpa_state=COMPLETED`, DHCP, routes, or autostart apps.

**Do not regress to:** blocking activate on WPA connect, or moving monitor polling into the handler or into asyncio in this PR. Matrix tests in `ACTIVATION_OUTCOMES.md` guard this.

### 4. Post the review reply

Use **Summary for reviewers** below in the PR thread.

---

## Don't

- **Don't replace `ConnectionMonitor` threads with `asyncio.Task` in this PR.** Underlying calls are sync subprocess; no user-visible gain, high churn and test risk.

- **Don't add a `list_configs` cache yet.** Validation-at-list-time is intentional (malformed configs appear as `"name (malformed)"` / `"name (empty)"`).

- **Don't increase gunicorn workers as a quick fix.** Network namespace state is process-global; multiple workers would cause correctness bugs.

- **Don't rewrite `run_command` / namespace services in this PR.** `to_thread` at the API boundary is sufficient for now.

---

## Defer (follow-up PRs)

| Item | Rationale |
|------|-----------|
| Lazy validation on `GET /network/config/` | Parse full JSON only on `GET /{id}` or on write |
| `to_thread` on remaining config CRUD handlers | Low impact today; apply for consistency |
| Async-native subprocess (`asyncio.create_subprocess_exec`) | Deeper refactor of `run_command` and services |
| Config list caching (mtime-based) | Only if config count or latency becomes measurable |
| Async-native monitor lifecycle | Tie background work to app lifespan when subprocess layer is async-capable |
| Background jobs + progress polling for activate/deactivate | Strategic UX improvement for multi-adapter configs |

---

## Strategic change (future architecture)

1. **Separate “fast API” from “slow network operations.”** Long-running activate/deactivate could return a job id and expose progress via polling — not hold the HTTP connection open even on a thread pool.

2. **Unify background work under one model.** Replace ad hoc daemon threads with lifecycle-aware tasks/jobs (same `monitor_key` ownership, cleaner shutdown).

3. **Measure before optimizing list validation depth.** Profile on target hardware with realistic config counts.

---

## Summary for reviewers

- **`list_configs()`:** valid note; low impact at expected scale; optional `current.txt` read-once hygiene in this PR; no cache yet.
- **`ConnectionMonitor` threads:** intentional; off the request path; not the cause of API-wide blocking.
- **This PR’s code fix:** `asyncio.to_thread()` in `network_config_api.py` for **activate, deactivate, status, and list** — keeps the event loop responsive on a single worker without changing network semantics.
- **Not a regression:** namespace/rollback work does not add new blocking patterns; the `to_thread` wrapper closes the gap the review identified on the worst endpoints.
