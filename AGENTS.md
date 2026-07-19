# Guidance for coding agents

Read this before changing code. It encodes lessons this codebase has already
paid for. WORKFLOW.md covers setup, building, and releases.

## Branch and PR rules

- PRs target `dev` (the default branch). `main` is the release line; never PR it.
- One concern per PR. One domain router, one fix, one refactor. No mixed
  move-plus-change diffs. Soft cap ~400 changed lines.
- CI-only or docs-only changes do not bump `debian/changelog`. A version bump
  is a release; only package-content changes get one.

## Writing tests

The test suite runs on Python 3.13 only (`tox -e py313`). It must be
deterministic and warning-clean. Hard rules, each one from a real failure:

1. **No wall-clock polling of mock state.** Never loop on `mock.called` with a
   deadline. Have the mock's `side_effect` set a `threading.Event` and wait on
   that event. Assert after synchronization, not after a sleep.
2. **Real threads need loud cleanup.** Any test that starts a monitor or
   background thread must stop it and wait for it to actually die before the
   test ends. Cleanup helpers must raise on timeout, never return silently: a
   leaked thread consumes the next test's mocks and fails an unrelated test.
3. **Patch where the code looks the name up.** If production does
   `from x import y` at module top, patch it at the consuming module, not at
   `x`. Lazy in-function imports are patched at the source module. Check the
   import style before writing the patch target.
4. **Shared mock sequences must be thread-safe.** A generator `side_effect`
   consumed by more than one thread corrupts silently. Use a lock plus index.
5. **Warning-clean or explicitly suppressed.** Tests that intentionally build
   invalid models (e.g. via `model_construct`) must scope-suppress the expected
   pydantic serializer warnings with `warnings.catch_warnings()` around the
   exact call. Never suppress globally; never leave expected warnings in the
   output, they bury real ones.
6. **No hardware or network access.** Tests run offline on CI runners. Anything
   touching wpa_supplicant, iw, dbus, or subprocesses is mocked. Hardware
   verification happens on a WLAN Pi, not in unit tests.
7. **Patching `x.time.sleep` patches stdlib `time` globally.** Modules that do
   plain `import time` all share the one `time` module object, so
   `patch("wlanpi_core.connection.monitor.time.sleep")` also no-ops the test's
   own `time.sleep` calls, turning polling loops into GIL-hogging busy-spins.
   Synchronize with `threading.Event.wait` (blocks in C, unaffected by the
   mock) instead of sleeping.
8. **Follow the matrix pattern.** Namespace scenarios live in
   `tests/scenarios/*.csv` with handlers in `tests/test_namespace_matrix/`.
   Add scenarios there rather than writing parallel one-off tests.

## OpenAPI docs

`docs/openapi.json` is generated (`scripts/export_openapi.py`) and maintained
by the sync workflow. Never hand-edit it; fix the source docstrings or
`openapi_docs.py` on `dev`. Placeholders like `<jwt>` in descriptions must sit
inside backticks or Swagger UI swallows them as HTML tags.
