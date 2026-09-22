# Guidance for coding agents

Read this first. WORKFLOW.md covers setup, building, and releases.

## Branch and PR rules

- PRs target `dev` (the default branch). `main` is the release line; never PR it.
- One concern per PR. One domain router, one fix, one refactor. No mixed
  move-plus-change diffs. Soft cap ~400 changed lines for focused changes.
- CI-only or docs-only changes do not bump `debian/changelog`. A version bump
  is a release; only package-content changes get one.
- Keep `wlanpi_core/__version__.py` in sync with the deb version minus the
  revision (e.g. `2.1.16` for `2.1.16-1`). The build/deploy checks fail if they
  diverge.

## Tooling and gates

All checks run through tox and are wired into CI workflows:
`python-lint-police.yml` (lint), `python-format-police.yml` (formatcheck),
`test-python-package.yml` (tests, which includes the OpenAPI freshness
check -- see `envlist` in `tox.ini`).

Before committing, run the gates that your change touches:

- `tox -e lint` : `ruff check wlanpi_core tests` then `mypy wlanpi_core`
- `tox -e formatcheck` : `ruff format --check wlanpi_core tests`
- `tox` : `envlist` runs both `py313` (the test suite plus coverage) and
  `openapicheck` (fails if `docs/openapi.json` is stale; see OpenAPI docs
  below). It's a normal env in `envlist`, not a conditional step someone has
  to remember to run -- a gate that's opt-in is a gate that gets skipped.

`tox -e format` rewrites the tree with `ruff format` when the check fails.

The lint and format gates must be green **on every commit**, not just at PR
time. If a gate fails on a change, fix the cause in the same change rather
than committing a red tree and planning to repair it later.

### Rules that bite

1. **mypy runs against the installed package.** The `lint` env deliberately
   omits `skip_install` so tox installs the package and its runtime deps;
   that is what lets mypy resolve `fastapi`, `sqlalchemy`, `dbus`, and so on.
   Do not add `skip_install = true` to `[testenv:lint]`, or every import
   becomes `import-not-found`.
2. **No bare generic annotations.** `mypy.ini` sets
   `disallow_any_generics`, so `dict`, `set`, `list`, and `tuple` need
   explicit type arguments. Follow the existing convention: JSON payloads are
   `dict[str, Any]`. Add `Any` to the existing `typing` import rather than a
   new import line.
3. **FastAPI endpoint docstrings are user-facing.** Each endpoint function's
   `__doc__` becomes the OpenAPI `description` for that endpoint (the route
   decorators do not set a `description=`). A missing, vague, or stale
   docstring shows up directly in the API reference. ruff enforces
   Google-convention docstrings (D100-D106 presence, D200/D205/D209/D401/D415
   format) on `wlanpi_core`; `tests/**` is exempt from the presence rules
   because test names self-describe.
4. **Line length is owned by the formatter.** `E501` is disabled; let
   `ruff format` wrap long lines. Do not hand-wrap to satisfy a linter that
   is off.
5. **Blind `except Exception` is allowed at API/service boundaries.**
   `BLE001` is deliberately ignored (as the old gate's `B902` rule was):
   endpoints catch `Exception`, log it, and return a 500/503 response rather
   than crash the request. Do not narrow these to appease a linter; do narrow
   an `except Exception` that wraps a single clearly-bounded operation.
6. **Whitespace is handled by ruff** (W291/W293) and `ruff format`. There are
   no whitespace scripts; do not reintroduce them.

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
docstrings or `openapi_docs.py` on `dev`. PRs into both `dev` and `main` are
gated on freshness (the OpenAPI Reference Check workflow, required on both
branches): if it fails on a PR into `dev`, regenerate and commit the result
in that PR; if it fails on a PR into `main`, merge the automation PR into
`dev` first. Placeholders like `<jwt>` in descriptions must sit inside
backticks or Swagger UI swallows them as HTML tags.

Regenerate with `tox -e openapi` (writes the file) or `tox -e openapicheck`
(fails on any diff, writes nothing) rather than running
`scripts/export_openapi.py` directly against whatever's in your venv.
`pyproject.toml`'s own dependencies are unpinned, so an ordinary install
pulls the newest fastapi/pydantic on PyPI; pydantic's JSON-schema output is
version-sensitive, so that can produce a `docs/openapi.json` that looks
right locally but still fails CI's diff against `requirements.txt`'s pinned
versions. Both tox envs install from `requirements.txt` to match CI exactly.

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
- Verify before committing: run the gates in "Tooling and gates"
  (`tox -e lint && tox -e formatcheck && tox`).

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
