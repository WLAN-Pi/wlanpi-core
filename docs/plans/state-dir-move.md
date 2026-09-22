# Plan: move wlanpi-core state from /home/wlanpi/.local to /home/wlanpi-core

**Status:** proposed, not started. Breaking change; intended as `wlanpi-core 2.3.0`.
**Blocked by:** WLAN-Pi/wlanpi-app#30 (the app hardcodes the old paths).
**Tracking:** WLAN-Pi/wlanpi-core#232.
**Closes:** #126 (`~/.local` created as root breaking other installs).

## Problem

`wlanpi-core` stores persistent state under
`/home/wlanpi/.local/share/wlanpi-core/`. The service runs as root, so on first
boot it root-creates `/home/wlanpi/.local` before the `wlanpi` user ever touches
their home directory. Subsequent installs that try to create
`/home/wlanpi/.local/share/<anything>` as the `wlanpi` user fail with
`Permission denied` (#126).

The XDG `~/.local/share` convention applies to apps running as the user who
owns the home directory. A root daemon writing into another user's home violates
that contract.

## Why /home and not /var/lib

FHS-canonical state for a system daemon is `/var/lib/<pkg>`. On the WLAN Pi
image, `/var` is wiped on every A/B image flip; only `/home` persists. Putting
state under `/var/lib` would invalidate all tokens and regenerate the shared
secret on every upgrade, breaking client auth. `/home` persistence is forced by
the image layout, so `/home/wlanpi-core` is the correct location despite being
an FHS deviation.

<!-- ponytail: /home instead of /var/lib is forced by A/B image persistence; revisit only if the partition layout changes. -->

## Why not a proper wlanpi-core system user

A system user pays off only if the service runs as it. `wlanpi-core` runs as
root because it manages network namespaces, mount operations, and dozens of
privileged `run_command` call sites (`ip`, `iw`, `wpa_cli`, `lldpctl`, mount,
ufw). De-rooting requires capability plumbing across all of those, a large
separate effort. Creating a system user whose home a root daemon writes into
adds a postinst `adduser` step and UID/GID migration complexity for zero
security benefit while the daemon is root. When de-rooting happens, create the
user then and `chown` the tree in postinst; the dir layout here does not change.

## Target layout

```
/home/wlanpi-core/          root:root 0755
├── secrets/                root:root 0700
│   ├── shared_secret.bin   root:root 0600
│   ├── tokens.db
│   └── fernet_key.b64
└── netcfg/                 root:root 0755
    ├── configs/
    ├── pids/
    ├── current.txt
    └── apps.json
```

Flat structure: the `.local/share/wlanpi-core` nesting only existed because XDG
was being (mis)followed. Inside a dedicated directory it adds nothing.

Since #179 the shared secret is root-only (`0600 root:root`) and the secrets
directory is `0700 root:root`. On-device clients authenticate with a JWT instead
of reading the secret, so no group-readable secret is needed. `security.py`
self-heals both permissions at startup, so no security-layer changes are
required here.

## Consumers of the current state paths

| File | Hardcoded path | Fix |
|---|---|---|
| `wlanpi_core/constants.py` | `HOME_DIR = /home/wlanpi` + derivations | New `STATE_DIR` constant |
| `wlanpi_core/cli/getjwt.py:25` | `SECRET_PATH` | Import `SHARED_SECRET_PATH` from constants |
| `wlanpi_core/cli/network_config.py:107` | `self.APPS_FILE` | Import `APPS_FILE` from constants |
| `scripts/lsdb.py:59` | `database_path` | Import `DATABASE_PATH` from constants |
| `debian/postinst` | `SECRETS_DIR` (#179 permission block) | Update to the new path, fold into the migration |
| `debian/postrm:17` | `rm -rf .../wlanpi-core/secrets` | Update path |
| `debian/wlanpi-core.service` | `RequiresMountsFor=/home/wlanpi` (from #157) | Update path |
| `install/usr/bin/wlanpi-core-preflight:18` | `STATE_DIR` (from #157) | Update path |
| `install/usr/bin/lhapitest:7,123` | `SECRETS_PATH` | Update path |
| `WORKFLOW.md:152` | openssl HMAC example | Update path |

`wlanpi-fpms`, `wlanpi-common`, and `wlanpi-mcp` do not reference the state
paths. `wlanpi-webui` does not either since #179 (it mints a JWT instead of
reading the secret).

Cross-repo: `wlanpi-app` hardcodes the old paths and must be updated in
lockstep (see Companion changes).

## Changes

### 1. `wlanpi_core/constants.py`

Replace `HOME_DIR` / `WLANPI_CORE_HOME_DIR` with `STATE_DIR` /
`WLANPI_CORE_STATE_DIR`. The old env var name is dropped deliberately: nothing
in-repo or in CI sets it, so the rename is a clean break with no migration.

```python
# /home is the only A/B-persistent partition on the WLAN Pi image; /var/lib
# would be wiped on every image flip. STATE_DIR must stay under /home.
STATE_DIR = Path(os.environ.get("WLANPI_CORE_STATE_DIR", "/home/wlanpi-core")).expanduser()

SECRETS_DIR = str(STATE_DIR / "secrets")
SHARED_SECRET_FILE = "shared_secret.bin"          # filename, resolved under secrets/
SHARED_SECRET_PATH = f"{SECRETS_DIR}/{SHARED_SECRET_FILE}"
ENCRYPTION_KEY_FILE = "fernet_key.b64"
DATABASE_PATH = f"{SECRETS_DIR}/tokens.db"
CONFIG_DIR = str(STATE_DIR / "netcfg" / "configs")
CURRENT_CONFIG_FILE = str(STATE_DIR / "netcfg" / "current.txt")
PID_DIR = str(STATE_DIR / "netcfg" / "pids")
APPS_FILE = str(STATE_DIR / "netcfg" / "apps.json")
```

Keep `SHARED_SECRET_FILE` and `ENCRYPTION_KEY_FILE` as bare filenames because
`security.py` resolves them against `secrets_path`. Delete the dead `HOME`
constant; nothing imports it.

### 2. Kill hardcoded path dupes

`cli/getjwt.py`, `cli/network_config.py`, and `scripts/lsdb.py` each hardcode
the path instead of importing from `constants`. Fix at source so the next move
is a one-liner:

- `cli/getjwt.py`: `from wlanpi_core.constants import SHARED_SECRET_PATH`; drop
  the `SECRET_PATH` local.
- `cli/network_config.py`: `from wlanpi_core.constants import APPS_FILE`; drop
  the `self.APPS_FILE` assignment.
- `scripts/lsdb.py`: `from wlanpi_core.constants import DATABASE_PATH`; drop the
  local.

### 3. `debian/postinst`

Migrate on upgrade, before the service starts, then repair #126:

```sh
OLD_STATE="/home/wlanpi/.local/share/wlanpi-core"
NEW_STATE="/home/wlanpi-core"

if [ -d "$OLD_STATE" ] && [ ! -d "$NEW_STATE" ]; then
    mkdir -p "$NEW_STATE"
    [ -d "$OLD_STATE/secrets" ] && mv "$OLD_STATE/secrets" "$NEW_STATE/secrets" || true
    [ -d "$OLD_STATE/netcfg"  ] && mv "$OLD_STATE/netcfg"  "$NEW_STATE/netcfg"  || true
    # Remove emptied tree; leave .local itself for the user.
    rmdir --ignore-fail-on-non-empty \
        "$OLD_STATE" /home/wlanpi/.local/share /home/wlanpi/.local 2>/dev/null || true
elif [ -d "$OLD_STATE" ]; then
    echo "postinst: warning: both $OLD_STATE and $NEW_STATE exist; skipping migration" >&2
fi

# Repair #126: restore ownership of .local to the wlanpi user in case an
# earlier install root-created it. Idempotent; safe if .local does not exist.
if [ -d /home/wlanpi/.local ]; then
    chown -R wlanpi:wlanpi /home/wlanpi/.local || true
fi

# Root-only secret permissions (from #179), now under the new path.
SECRETS_DIR="$NEW_STATE/secrets"
if [ -d "$SECRETS_DIR" ]; then
    chown root:root "$SECRETS_DIR" 2>/dev/null || true
    chmod 0700 "$SECRETS_DIR" 2>/dev/null || true
    if [ -f "$SECRETS_DIR/shared_secret.bin" ]; then
        chown root:root "$SECRETS_DIR/shared_secret.bin" 2>/dev/null || true
        chmod 0600 "$SECRETS_DIR/shared_secret.bin" 2>/dev/null || true
    fi
fi
```

Fresh installs: `SecurityManager` mkdirs `/home/wlanpi-core/secrets` on first
start. Nothing writes to `/home/wlanpi`, so #126 cannot recur.

### 4. `debian/postrm`

```sh
# remove
rm -rf /home/wlanpi-core/secrets
# purge
rm -rf /home/wlanpi-core
```

### 5. `debian/wlanpi-core.service`

```ini
RequiresMountsFor=/home/wlanpi-core /var/log/wlanpi_core
```

Update the stale comment that says the path flip is a later PR.

### 6. `install/usr/bin/wlanpi-core-preflight`

```sh
STATE_DIR="/home/wlanpi-core/secrets"
```

Update the "CURRENT paths under /home/wlanpi" comment.

### 7. `install/usr/bin/lhapitest`

Update `SECRETS_PATH` and its help text to
`/home/wlanpi-core/secrets/shared_secret.bin`.

### 8. `WORKFLOW.md`

Update line 152:

```sh
"$(cat /home/wlanpi-core/secrets/shared_secret.bin)"
```

### 9. `debian/changelog`

New `2.3.0-1` entry (breaking package-content change; version bump required),
and `wlanpi_core/__version__.py` to `2.3.0`.

## Companion changes

- **`wlanpi-app` (required, blocks this):** update the five hardcoded paths in
  `lib/services/token_handler.dart` (`:219`, `:257`, `:271`) and
  `lib/pages/network_page/network_page.dart` (`:176`, `:214`) from
  `/home/wlanpi/.local/share/wlanpi-core` to `/home/wlanpi-core`. Tracked in
  WLAN-Pi/wlanpi-app#30. Do not ship the core move without it.
- **`wlanpi-webui`:** no change. It does not read the secret (#179); it mints a
  JWT through `getjwt`, which follows `SHARED_SECRET_PATH` automatically.
- **`wlanpi-mcp`:** no change. It reaches core over its URL and does not touch
  the state paths.

## Tests

No new unit tests. The constants change is a one-line `os.environ.get`
(overriding it would test stdlib, not our logic). The risky part is the postinst
migration shell, covered by `bash -n` plus the device smoke test before release.
The existing suite never touches the filesystem at import time, and nothing sets
`WLANPI_CORE_HOME_DIR`.

## Downgrade behaviour

Downgrading from a post-move package to a pre-move package: the old package
finds nothing at the old path, `SecurityManager` regenerates secrets, tokens are
invalidated. No compat shim: this is a one-way package upgrade path on an
appliance and token loss on downgrade is acceptable.

## Sequencing

1. This PR: state move, `2.3.0`.
2. Device smoke test (fresh install and upgrade), then close #126.
