# WLAN Pi core development workflow

This document covers development workflow specific to wlanpi-core. For general Git workflow and contribution guidelines, see the [WLAN Pi contributing guide](https://github.com/WLAN-Pi/developers/blob/main/CONTRIBUTING.md).

## Table of Contents

* [Quick setup](#quick-setup)
* [Setup development environment](#setup-development-environment)
* [Developing](#developing)
* [Authentication and testing](#authentication-and-testing)
* [Troubleshooting](#troubleshooting)
* [Versioning and releases](#versioning-and-releases)
* [Code quality](#code-quality)
* [Building the package](#building-the-package)

## Quick setup

Run `./init` from the base folder of this repo to install system depends, create the virtual environment (venv), install Python depends, and run the `wlanpi_core` module directly on the default port.

After you've done `./init`, you can use `./run` to skip all the staging. This _should_ work. If it doesn't, please open an issue so we can get it resolved for future use. Note that you may need to run `./init` again if depends are updated in the future.

## Setup development environment

 1. Clone repo
 1. Create your feature or fix branch from the `dev` branch 
 1. Create virtualenv
 1. Install wheel and setuptools in virtualenv
 1. Install package into virtualenv with extras

```bash
git clone git@github.com:WLAN-Pi/wlanpi-core.git 
cd wlanpi-core
python3 -m venv venv && source venv/bin/activate
pip install -U pip pip-tools wheel setuptools 

# developers should install test depends also like so
pip install .[testing]
```

## Developing

Once you've 1) setup the virtualenv, 2) installed Python requirements, and 3) setup OS and package requirements, you can start developing by running wlanpi_core directly. 

There are two options to run directly:

### Option 1: Direct module execution

Run with auto-reload for development:

```bash
sudo venv/bin/python -m wlanpi_core --debug --reload
```

This will start the development server on http://127.0.0.1:8000 (loopback only, plain HTTP).
Production traffic goes through nginx on HTTPS port 31415; the dev server is separate.

When running directly, you can interact with these URLs:

- API frontend: http://127.0.0.1:8000
- Swagger UI documentation: http://127.0.0.1:8000/documentation

### Option 2: Running development version in place (symlink method)

Use this to test your development code using the production service configuration:

1. Verify the current working directory symlink:
   ```bash
   ls -l /opt/wlanpi-core/workingdirectory
   ```

2. Link to your development location:
   In this case, I have `wlanpi-core` cloned to `~`. Adjust accordingly.
   ```bash
   sudo ln -sfn /home/wlanpi/wlanpi-core/wlanpi_core /opt/wlanpi-core/workingdirectory
   ```

3. Restart the service:
   ```bash
   sudo systemctl restart wlanpi-core.service
   sudo systemctl status wlanpi-core.service
   ```

4. When done testing, restore the original symlink:
   ```bash
   sudo ln -sfn /opt/wlanpi-core/lib/python3.9/site-packages/wlanpi_core /opt/wlanpi-core/workingdirectory
   sudo systemctl restart wlanpi-core.service
   ```

### Option 3: Running with gunicorn (socket binding)

For testing with the exact production setup:

1. Elevate to root and activate the venv:
   ```bash
   sudo su --
   source venv/bin/activate
   ```

2. Stop the installed services:
   ```bash
   systemctl stop wlanpi-core.service && systemctl stop wlanpi-core.socket
   ```

3. Start your development copy with socket binding:
   ```bash
   gunicorn --workers 1 --reload -k uvicorn.workers.UvicornWorker --bind unix:/run/wlanpi_core.sock wlanpi_core.asgi:app
   ```

4. For direct API access (safe networks only):
   ```bash
   ufw allow 31415
   ```
   Then access at `https://wlanpi-###.local:31415/` or `https://<ip>:31415/`
   (trust the self-signed cert at `/etc/nginx/ssl/self-signed-wlanpi.cert`)

5. When done, restart original services:
   ```bash
   systemctl stop wlanpi-core.socket && systemctl stop wlanpi-core.service
   ```

## Authentication and testing

### Creating JWT tokens

The `getjwt` helper script generates JSON Web Tokens (JWTs) for bootstrapping
authentication. It signs the request with core's shared HMAC secret, which is
root-only, so run it with `sudo`:

```bash
# Basic usage
sudo getjwt my-device-123

# With custom port
sudo getjwt my-device-123 8000
```

Keep tokens in the environment or a keychain on the client machine, not in an
MCP client config file where they sit in cleartext. On the device, print an
export line and copy it into the client shell:

```bash
sudo getjwt my-device-123 --export
```

Do not pipe `sudo getjwt` over `ssh`: sudo needs a TTY, and `ssh -t` folds the
password prompt into the captured output, so `eval "$(ssh ...)"` is unreliable.

### Manual HMAC authentication test

```bash
canonical_string="POST\n/api/v1/auth/token\n\n{\"device_id\": \"testing\"}"
signature=$(printf "$canonical_string" | openssl dgst -sha256 -hmac "$(cat /home/wlanpi/.local/share/wlanpi-core/secrets/shared_secret.bin)" -binary | xxd -p -c 256)

curl -X 'POST' \
  --cacert /etc/nginx/ssl/self-signed-wlanpi.cert \
  -H "X-Request-Signature: $signature" \
  'https://127.0.0.1:31415/api/v1/auth/token' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{"device_id": "testing"}'
```

### Using lhapitest

`./install/usr/bin/lhapitest` (installed as `/usr/bin/lhapitest`) signs localhost requests with the shared secret. Run it with `sudo` so it can read the secret file; add `-v` to print the canonical string and signature.

```bash
# Default port (31415)
./install/usr/bin/lhapitest -X POST -e /auth/token -P '{"device_id": "testing"}'
./install/usr/bin/lhapitest -e /system/device/model

# Dev server (loopback HTTP, no TLS — not for production)
./install/usr/bin/lhapitest -X POST -e /auth/token -P '{"device_id": "testing"}' -p 8000 --http
./install/usr/bin/lhapitest -e /system/device/model -p 8000 --http
```

**Note:** Localhost applications use HMAC signatures. External applications **must** authenticate using JWT tokens.

## Troubleshooting

### Service logs

```bash
# View service logs
journalctl -u wlanpi-core

# Follow logs in real-time
journalctl --follow --unit wlanpi-core
journalctl -f -b -u wlanpi-core
journalctl -f -n 10 -u wlanpi-core
```

### Application logs

```bash
# Last 20 lines with follow
tail -n 20 -f /var/log/wlanpi_core/app.log
tail -n 20 -f /var/log/wlanpi_core/debug/debug.log
```

### tmpfs debugging

Check the debug log tmpfs mount:

```bash
systemctl status var-log-wlanpi_core-debug.mount
mount | grep wlanpi_core/debug
df -h /var/log/wlanpi_core/debug
ls -la /var/log/wlanpi_core/debug
```

Example output:

```
$ systemctl status var-log-wlanpi_core-debug.mount
● var-log-wlanpi_core-debug.mount - Debug log tmpfs mount for wlanpi-core
     Loaded: loaded (/lib/systemd/system/var-log-wlanpi_core-debug.mount; enabled; vendor preset: enabled)
     Active: active (mounted) since Tue 2025-01-14 09:25:03 CST; 2min 44s ago
      Where: /var/log/wlanpi_core/debug
       What: tmpfs

$ mount | grep wlanpi_core/debug
tmpfs on /var/log/wlanpi_core/debug type tmpfs (rw,relatime,size=25600k,mode=750,uid=1000)

$ df -h /var/log/wlanpi_core/debug
Filesystem      Size  Used Avail Use% Mounted on
tmpfs            25M   12K   25M   1% /var/log/wlanpi_core/debug
```

## Versioning and releases

### For maintainers

Merge strategy between dev (development) and main (release branch)

**NEVER use squash merges when merging between `dev` and `main`.** 

Please always use regular merge commits (`git merge --no-ff`).

**Why?** Squash merging between permanent branches destroys the shared commit history, making it impossible for Git to track which commits exist in both branches.

This leads to:

- Inability to merge main back into dev without massive conflicts
- Branch divergence that cannot be reconciled
- Loss of detailed commit history on the release branch

Regular merge commits preserve the full history and keep both branches properly synchronized.

**Summary:**

- ✅ **Squash merge OK**: `feature/branch` → `dev` (keeps dev clean of the many commits a feat/fix may take)
- ❌ **Regular merge REQUIRED**: `dev` → `main` (preserves shared history)
- ❌ **Regular merge REQUIRED**: `main` → `dev` (preserves shared history)

### Version locations

Before cutting a release, confirm the **OpenAPI Reference Check** is green on
the dev→main PR. If it fails, `docs/openapi.json` is stale: merge the open
`chore: update generated OpenAPI reference` PR into `dev` (the sync workflow
keeps one current) and the release PR re-runs green.

Each release requires versions to be updated in **two** locations:

1. **Debian changelog**: `debian/changelog` via `dch` (`devscripts`)
   ```bash
   dch -i  # Create new changelog entry
   ```

2. **Python package**: `wlanpi_core/__version__.py` (manual edit)

Python package versioning should follow [PEP 440](https://www.python.org/dev/peps/pep-0440/).

### Tagging

Create annotated tags for releases:

```bash
git tag -a v1.2.3 -m "Release 1.2.3"
git push origin v1.2.3
```

For complete release procedures, see [Release Process](https://github.com/WLAN-Pi/developers/blob/main/RELEASE_PROCESS.md).

## Code quality

Before committing, run the quality checks:

```bash
# Format code
tox -e format

# Lint code
tox -e lint

# Run tests (also checks docs/openapi.json is current -- see tox.ini's envlist)
tox
```

Install dependencies with either:
- `pip install .[testing]` 
- Or use `./init` which handles this

## Building the package

From the root directory:

```bash
dpkg-buildpackage -us -uc -b
```

See [PACKAGING.md](PACKAGING.md) for detailed packaging information.

## See also

- [Contributing guide](https://github.com/WLAN-Pi/developers/blob/main/CONTRIBUTING.md) - General Git workflow and contribution guidelines
- [Release process](https://github.com/WLAN-Pi/developers/blob/main/RELEASE_PROCESS.md) - Detailed release procedures
- [PACKAGING.md](PACKAGING.md) - Packaging standards for this repo
- [Gunicorn settings documentation](https://docs.gunicorn.org/en/stable/settings.html#debugging)
