# Guidance for coding agents

Read this first. WORKFLOW.md covers setup, building, and releases.

## Branch and PR rules

- PRs target `dev` (the default branch). `main` is the release line; never PR it.
- One concern per PR. One domain router, one fix, one refactor. No mixed
  move-plus-change diffs. Soft cap ~400 changed lines for focused changes.
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
by the sync workflow, which keeps a `chore: update generated OpenAPI
reference` PR open against `dev`. Never hand-edit it; fix the source
docstrings or `openapi_docs.py` on `dev`. Release PRs to `main` are gated on
freshness: if the OpenAPI Reference Check workflow fails, merge the
automation PR into `dev` first. Placeholders like `<jwt>` in descriptions
must sit inside backticks or Swagger UI swallows them as HTML tags.

## Before you write

Reuse first, write second:

- Grep `wlanpi_core/utils/`, `core/`, `models/`, `schemas/`, and the existing
  services before adding a module, endpoint, or helper. This repo already paid
  for these.
- New endpoints go in the existing routers (`api/api_v1/endpoints/`).
- A dependency already installed (`httpx`, `requests`, `aiosqlite`, `psutil`,
  `sqlalchemy`, ...) covers most needs. Adding a new one is a package-content
  change: it bumps `debian/changelog` and needs a human OK.

## Cost and scope

- Smallest diff that fixes the issue. No speculative abstraction, no config for
  a value that never changes, no helper with one caller.
- Delete over add; boring over clever.
- No walrus operator (`:=`). Rewrite the assignment into a plain statement;
  readability beats the one-liner.
- Mark deliberate simplifications that cut a real corner (a global lock, an
  O(n²) scan, a naive heuristic) with a `# shortcut:` comment naming the
  ceiling and the upgrade path.
- Be terse in replies and in what you read. Prefer `grep`/`glob` and targeted
  reads over dumping whole files. Run the real gates once, not ad-hoc
  exploratory commands.
- Stop and ask the human before: creating a new top-level module or router
  file, or when scope is ambiguous. Don't spend 20 tool calls on a decision a
  human answers in one message.
- Verify before committing: `tox -e lint && tox -e formatcheck && tox -e py313`.

## Documentation

Write technical documentation using Diátaxis: tutorials teach, how-to guides
solve a task, reference documents the interface, and explanations provide
conceptual context. Choose one primary type per page.

Use clear, direct, task-oriented prose. Verify all technical statements against
the repository. Include prerequisites, exact commands or complete examples, and
a way to verify success where applicable. Do not invent behavior or duplicate
canonical reference material.

### House style

- Address the reader as "you."
- Use present tense and active voice.
- Start task pages with the goal and prerequisites.
- Use numbered steps for ordered actions and bullets for unordered facts.
- Put commands in fenced code blocks; put expected output immediately after.
- Use literal spelling for commands, paths, flags, config keys, and values.
- Use one canonical term for each concept.
- Never use emdashes; use commas or parentheses, or rewrite the sentence.
- Avoid filler such as "simply," "just," "obviously," and "easy."
- Warn immediately before destructive, privileged, costly, or production-impacting steps.
- Link to the canonical reference instead of duplicating option details.
