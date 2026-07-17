# P0 API test matrix

**Status:** Active  
**Related:** [P0-core-worker-api.md](./P0-core-worker-api.md), [p0-api-gap-matrix.csv](./p0-api-gap-matrix.csv)

## Why continue the matrix approach?

The namespace work used `namespace_test_matrix.csv` + parametrized handlers successfully:

- Every row is a **reviewable scenario** (positive, negative, recovery, hw-absence).
- Permutations stay visible in a spreadsheet — not buried in pytest code.
- **CI stubs are explicit per row** — reviewers see exactly what is mocked and why.
- Handler registry grows incrementally as endpoints ship.

**Recommendation: yes — use the same pattern for P0 API work.**

| Namespace matrix | P0 API matrix |
|------------------|---------------|
| `namespace_test_matrix.csv` | `p0_api_test_matrix.csv` |
| `ACTIVATION_OUTCOMES.md` | `P0_API_OUTCOMES.md` |
| `tests/test_namespace_matrix/` | `tests/test_p0_api_matrix/` (scaffold) |
| Adapter PHY/iface conditions | HTTP request + expected status + adapter layout |

## Mocking policy (agreed)

```
┌─────────────────────────────────────────────────────────┐
│  REAL in CI: FastAPI app, routing, auth, Pydantic,    │
│              service orchestration, response shaping    │
├─────────────────────────────────────────────────────────┤
│  STUB only for hardware adapter layout:               │
│    0 monitor / 1 monitor / 2+ monitor / 0 total       │
│    → patch adapter enumeration or config/status parse │
├─────────────────────────────────────────────────────────┤
│  STUB CLI wrappers (not adapter hardware):            │
│    wlanpi-timezone, speedtest, ip route, etc.         │
│    → patch run_command with fixture output            │
├─────────────────────────────────────────────────────────┤
│  NAMESPACE DEEP TESTS: keep in namespace_test_matrix  │
│    (activate, rollback, ConnectionMonitor)            │
└─────────────────────────────────────────────────────────┘
```

On-device integration and fpms2 smoke tests run with minimal stubbing.

## Files

| File | Role |
|------|------|
| [`tests/scenarios/p0_api_test_matrix.csv`](../tests/scenarios/p0_api_test_matrix.csv) | Scenario spreadsheet (open in Excel/Sheets) |
| [`tests/scenarios/P0_API_OUTCOMES.md`](../tests/scenarios/P0_API_OUTCOMES.md) | Outcome semantics (scan selection, mode switch, auth) |
| [`tests/scenarios/p0_loader.py`](../tests/scenarios/p0_loader.py) | CSV loader (`ApiScenario` dataclass) |
| [`tests/test_p0_api_matrix/`](../tests/test_p0_api_matrix/) | Parametrized pytest (handlers added per endpoint) |

## Matrix columns

| Column | Meaning |
|--------|---------|
| **Test scope** | `positive`, `negative`, `deprecate`, `integration`, `ui-helper` |
| **API test name** | Handler key (unique) |
| **Precondition** | Device mode, active config, auth state |
| **Hardware adapters** | Monitor/managed layout — **only column that stubs hardware discovery** |
| **Request** | Method + path + body |
| **Expected HTTP** | Status code |
| **CI stubs** | Explicit patch targets for this row |
| **Runs real** | What executes without mock |

## Current scenario inventory (31 rows)

| Scope | Count | Examples |
|-------|-------|----------|
| positive | 20 | JWT issue, scan auto-select, mode switch force, timezone |
| negative | 4 | Auth missing, mode conflict, scan no adapter, service denied |
| deprecate | 3 | Legacy wlan scan/connect/set-dbus repurposing |
| integration | 1 | fpms2 P0 smoke list |
| ui-helper | 1 | wlanpi-ui adapter summary translation |

Add rows as each P0 endpoint ships. Update row count assertion in `test_matrix.py` when handlers exist.

## Workflow for adding a scenario

1. Add row to `p0_api_test_matrix.csv`.
2. If new outcome type, document in `P0_API_OUTCOMES.md`.
3. Implement handler in `tests/test_p0_api_matrix/handlers.py`.
4. Register in `HANDLERS` dict.
5. Run `pytest tests/test_p0_api_matrix/ -v`.

## Relationship to namespace matrix

| Concern | Matrix |
|---------|--------|
| `activate_config` persist vs rollback | `namespace_test_matrix.csv` |
| `ConnectionMonitor` timeout / delayed SSID | `namespace_test_matrix.csv` |
| HTTP scan adapter selection | `p0_api_test_matrix.csv` |
| Mode switch guard with active config | `p0_api_test_matrix.csv` |
| JWT auth on API routes | `p0_api_test_matrix.csv` |

Do not duplicate namespace activation permutations in the API matrix — call through to existing namespace tests or use a single integration row.

## Review checklist

- [ ] Row states positive **and** negative case where applicable?
- [ ] Hardware column empty or stub-only for non-scan tests?
- [ ] CI stubs column empty when test is fully real?
- [ ] Legacy DBus rows marked `deprecate` scope?
- [ ] Entry point names the handler under test?
