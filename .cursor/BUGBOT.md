# Bugbot review rules for wlanpi-core

`wlanpi-core` is the on-device FastAPI service for a WLAN Pi (Raspberry Pi). Production is one gunicorn worker (`uvicorn.workers.UvicornWorker`) bound to the unix socket `/run/wlanpi_core.sock`, with nginx terminating TLS on port 31415. It can change network config, start systemd units, capture packets, and shell out to `iw`, `ip`, `wpa_cli`, and similar tools. Python 3.13 only. License stays BSD-3-Clause.

Flag defects below. Skip style nits that ruff, mypy, or CI already enforce, and skip advice that would apply to any Python repo.

## Do not flag

- Line length, import order, or wrapping. `ruff format` owns those (`E501` is off). Do not ask for hand-wrapping.
- `except Exception` at an API or service boundary that logs and returns 500 or 503. `BLE001` is ignored on purpose. Do flag an `except Exception` that wraps one clearly bounded call and swallows a specific failure.
- Missing docstrings under `tests/**`. Test names self-describe. Do flag a missing, vague, or stale docstring on a route function: FastAPI publishes `__doc__` as the OpenAPI description. Route decorators do not set `description=`.
- A missing edit to `debian/changelog` or `wlanpi_core/__version__.py`. Only a release pull request changes those files.
- Raising `--workers` above 1, or replacing `ConnectionMonitor` threads with asyncio tasks. Namespace and wpa state are process-global, and the monitor stays off the request path.
- `setup.py`. It is a pybuild shim. Metadata lives in `pyproject.toml`.
- Existing `actions/checkout` and `actions/setup-python` major-version tags. Do flag a new third-party action that is not pinned to a commit SHA.

## Python, typing, and tests

- `mypy.ini` sets `disallow_untyped_defs` and `disallow_any_generics`. Flag bare `dict`, `list`, `set`, or `tuple`. JSON payloads are `dict[str, Any]`.
- Do not add `skip_install = true` to `[testenv:lint]`. mypy resolves fastapi, sqlalchemy, and dbus from the installed package.
- No walrus operator (`:=`).
- Tests run on Python 3.13 only (`tox -e py313`), offline, and must stay warning-clean. Flag new network, dbus, `iw`, wpa_supplicant, or real subprocess use in tests. Hardware checks belong on a device.
- Flag a test that polls `mock.called` with a deadline or sleeps to wait. The mock's `side_effect` should set a `threading.Event`. Flag a test that starts a monitor or background thread and does not stop it and wait, with cleanup that raises on timeout.
- Patch where the name is looked up. A top-level `from x import y` is patched on the consumer. A lazy in-function import is patched on the source module.
- Flag `patch("...time.sleep")`. Modules share the stdlib `time` module, so the patch also no-ops the test. Synchronize with `threading.Event.wait`.
- A generator `side_effect` shared by more than one thread needs a lock. `model_construct` of an invalid model needs `warnings.catch_warnings()` around that call only.
- New namespace scenarios go in `tests/scenarios/*.csv` with handlers in `tests/test_namespace_matrix/`, not a parallel one-off test.
- Behavior changes need a test. Flag a route, service, or migration change with no covering test.

## API and endpoints

- New routes go in an existing router under `wlanpi_core/api/api_v1/endpoints/` and are registered in `wlanpi_core/api/api_v1/api.py`. The public prefix is `/api/v1` (`API_V1_STR`). Flag a new top-level router module.
- Every route needs `Depends(verify_auth_wrapper)` or a stricter dependency. Flag a new unauthenticated route. Localhost HMAC (`X-Request-Signature`) is only for loopback. External callers use a JWT bearer token. PAM and other localhost-only routes use `verify_local_auth`, and a bearer there must be device id `wlanpi-webui` (`PAM_CLIENT_DEVICE_ID`).
- `is_localhost_request` trusts the peer and `X-Real-IP`, and requires a loopback address. Flag a check that treats `X-Forwarded-For` as the client, or that allows HMAC from a non-loopback peer.
- HMAC compares with `hmac.compare_digest`. JWT checks go through `token_manager.verify_token`. An auth clock that is not set (`AUTH_CLOCK_NOT_SET`) must fail closed. Flag a path that accepts a token without verification or logs the shared secret, JWT, PSK, or password.
- Request and response bodies use pydantic models in `wlanpi_core/schemas/` with `response_model` set. Flag a new route that returns an untyped dict as its contract.
- Keep live response shapes stable. A removed route returns 410 with `error: ENDPOINT_DEPRECATED` and a `replacement`, stays tagged `deprecated`, and is listed in `docs/API-DEPRECATED-ENDPOINTS.md`. Flag a silent removal or a shape change with no docs note.
- A docstring or schema change that alters the OpenAPI document must regenerate `docs/openapi.json` with `tox -e openapi` (deps from `requirements.txt`, not a loose venv). Flag a hand edit of that file, or a schema or docstring change that leaves it stale. Placeholders such as `<jwt>` in descriptions must sit inside backticks.
- The rate limit is per client (`slowapi`, default `90/minute` in `wlanpi_core/app.py`). Flag a global limiter that lets one busy client 429 the WebUI and other local callers.
- Reuse `wlanpi_core/services/`, `schemas/`, `models/`, and `utils/` before adding a helper. Flag a one-caller wrapper or a new dependency when `httpx`, `requests`, `aiosqlite`, `psutil`, or `sqlalchemy` already covers the job.

## Database and Alembic

- SQLAlchemy models live in `wlanpi_core/core/models.py` on `Base` in `wlanpi_core/core/database.py`. Sessions are async. Flag a sync engine or session mixed into a request path.
- Startup calls `Base.metadata.create_all`, which creates missing tables and does not alter columns on an existing `tokens.db`. Flag a model, column, constraint, or index change with no new revision under `alembic/versions/`. `alembic/env.py` binds `Base.metadata` and `DATABASE_PATH`. Flag an `alembic.ini` `sqlalchemy.url` change that points migrations at a different database.
- The token database is SQLite at `/home/wlanpi/.local/share/wlanpi-core/secrets/tokens.db`. Flag a second database, or unbounded queries of token and activity tables on the request path.

## Dependencies

- Runtime dependencies are unpinned in `pyproject.toml` `[project].dependencies` and in `requirements.in`. `requirements.txt` is the lockfile: `pip-compile --no-index requirements.in`, with the piwheels `--extra-index-url` kept. Flag a `requirements.in` edit that does not regenerate `requirements.txt`, or a new import whose distribution is missing from either file.
- A new dependency needs a human to accept it. Do not ask for a `debian/changelog` edit in that pull request. `dbus-python` is built from the sdist in `debian/rules` (no binary wheel). The pin is the single line in `debian/dbus-python.pin`. `debian/rules` and the openapi tox envs install that line. It stays out of `requirements.in` because Dependabot's pip-compile image has no libdbus and cannot build that sdist. Flag a casual change to that pin, putting `dbus-python` back in `requirements.in`, or a change to the `--preinstall` versions in `override_dh_virtualenv`.

## Debian packaging, versions, and paths

- Flag a fix or feature pull request that edits `debian/changelog` or `wlanpi_core/__version__.py`, or that adds a Debian revision (`-N`). Only a release pull request changes those files. On a release, the changelog version has no Debian revision, and `__version__.py` is that same `major.minor.patch`. The version check fails if they diverge. Do not add a git tag by hand. The procedure is [Land a Fix and Cut a Release](https://github.com/WLAN-Pi/developers/blob/main/RELEASING.md).
- Dev-build stamping is planned and is not live. When it is live, CI stamps the next patch in the workspace as `X.Y.Z~dev<YYYYMMDD>.<run_id>.<run_attempt>+g<sha>`, uploads that `.deb` to Packagecloud `wlanpi/dev`, and does not tag it. A release pull request uploads to `wlanpi/main` and tags `v<version>`. Do not flag a missing stamp in the diff.
- `debhelper-compat (= 13)` stays in `debian/control`. Do not add `debian/compat`. `Architecture: any` stays, because the package builds native extensions.
- Install root is `/opt/wlanpi-core` (`DH_VIRTUALENV_INSTALL_ROOT` and `--install-suffix wlanpi-core`). The unit `WorkingDirectory` is the stable symlink `/opt/wlanpi-core/workingdirectory`, which `debian/postinst` points at `site-packages/wlanpi_core`. Flag a unit or script that hardcodes `python3.x/site-packages`.
- `wlanpi-core.socket` `ListenStream`, gunicorn `--bind`, and the nginx `proxy_pass` must all stay `unix:/run/wlanpi_core.sock`. Flag a drift.
- `debian/rules` installs `wlanpi-core.service`, `wlanpi-core.socket`, `var-log-wlanpi_core-debug.mount`, and `wlanpi-core-ufw-first-boot.service` with `--no-start`. `postinst` starts them once. Flag a per-unit restart on install. `StartLimitBurst=5` / `StartLimitIntervalSec=60` is easy to burn.
- Config belongs in `/etc/wlanpi-core/`. Logs belong in `/var/log/wlanpi_core/` (`app.log` is persistent INFO and above). `/var/log/wlanpi_core/debug` is a tmpfs mount (`var-log-wlanpi_core-debug.mount`, rotated at 4 MiB). Variable data and secrets belong under `/home/wlanpi/.local/share/wlanpi-core/`. Runtime pidfiles belong in `/run/wlanpi-core`. Flag secrets, PSKs, tokens, or the Fernet key written under `/opt`, `/tmp`, or a world-readable path.
- Secrets directory mode is `0700` and `root:root`. `shared_secret.bin` and netcfg JSON profiles are `0600`, as are `/etc/wpa_supplicant/wlan[0-9]*.conf`. `postinst` repairs older installs. Flag a relaxation of those modes, or a `chown` of `/home/wlanpi/.local` away from `wlanpi:wlanpi` (except the secrets directory, which is root).
- Maintainer scripts and other packaged shell are `shellcheck` clean (`lint.yml`, warning severity) and use `set -e`. Device-side actions in `postinst` stay inside `if ! ischroot`.

## Security

This process runs as root and mutates the device. Treat interface names, namespace names, phy names, config ids, VLAN ids, SSIDs, service names, and file paths from the request as untrusted.

- Shell out through `run_command` or `run_command_async` with an argument list and `shell=False`. Flag new `shell=True`, `create_subprocess_shell`, or an f-string, `%` format, or concatenation that puts request data into a command string. `shlex.split` does not make a user-controlled string safe. The constant `shell=True` calls in `system_service` for memory, disk, and uptime are not a pattern to copy.
- Commands need a timeout (`COMMAND_TIMEOUT_SEC` is 30, speedtest is `SPEEDTEST_TIMEOUT_SEC`). Flag a `subprocess` call with no timeout.
- Names that cross into `ip`, `iw`, `wpa_cli`, or filenames go through `wlanpi_core/utils/validation.py` (`validate_interface_name`, `validate_namespace_name`, `validate_config_id`, `validate_phy_name`, `validate_vlan_id`, `validate_ssid`). Flag a privileged command built from a raw path or query parameter. Namespace names reject `@` so they cannot collide with `ROOT_NS_DIR_NAME`.
- Start, stop, restart, and status of systemd units go through `is_allowed_service` (`allowed_services` in `system_service`). Flag a route that passes an arbitrary unit to systemd or `systemctl`.
- Do not log request bodies, canonical HMAC strings, or `wpa` config contents. Network profiles hold PSKs.
- The dev server binds `127.0.0.1:8000` (plain HTTP). Flag a bind to `0.0.0.0` or a non-loopback address. Production traffic stays on the unix socket behind nginx.
- Flag a new default password, embedded secret, or disabled TLS check on a call that leaves the device.

## Performance on the Pi

- One event loop serves every client. Flag synchronous file I/O, dbus, or subprocess work inside an `async def` route that is not in `asyncio.to_thread` or `run_command_async`. Flag `time.sleep` in async code.
- Do not block activate on `wpa_state=COMPLETED`, DHCP, or routes. Secured activate returns once the profile is provisioned and the monitor is running.
- A Wi-Fi scan already in flight on an adapter returns `SCAN_IN_PROGRESS` and must not start a second scan. Flag a new scan, speedtest, or neighbor poll that runs once per caller with no coalesce and no timeout.
- `app.log` stays INFO and above. Debug logging is capped by a small tmpfs. Flag per-packet or per-poll INFO logs.
- Cache hot, volatile reads (scan, link state) inside core with a short TTL if a new endpoint would otherwise rerun the same subprocess for every consumer. Do not cache tokens, HMAC results, or other per-caller auth data in a shared cache. Device identity is already `lru_cache`d. Operating mode is not, and must stay live.
- Journald endpoints report and switch storage. They must not change the image default on their own.

## Scope

- One concern per PR. Flag a diff that mixes a behavior change with a move, rename, or format-only sweep.
- Flag a `# ponytail:` shortcut (global lock, quadratic scan, naive heuristic) that does not name its ceiling and the upgrade path.
- Ethernet listing is by link type, not an `eth*` name prefix. USB adapters named `enx*` are included. Wi-Fi, USB gadget, bridge, and VLAN links stay excluded. SSIDs are UTF-8 text, not `iw` or `wpa_cli` escape sequences. Monitor netdevs are `wlanpi<phy index>`.
- Above 500 changed lines the PR description needs a `## Review order` section. Above 1,000 it also needs why the change cannot be split. The `pr-size` check is advisory, but flag a huge mixed diff that has neither.
