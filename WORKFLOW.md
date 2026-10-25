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
 1. Create your feature or fix branch from the `main` branch
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
# -F keeps following debug.log after it rotates to debug.log.1
tail -n 20 -F /var/log/wlanpi_core/debug/debug.log
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

`main` is the only long-lived branch. Every pull request targets `main`.
Squash-merge a fix or a feature so it lands as one commit.

A fix or feature pull request does not edit `debian/changelog` or
`wlanpi_core/__version__.py`. Do not run `dch`. Do not add a Debian revision
(`-N`). Only a release pull request changes those files. In the fix or feature
pull request, write one line that says what changed for the person installing
the package. Use that line as the squash-merge subject.

Dev-build stamping is planned and is not live. When it is live, CI stamps the
next patch in the build workspace and does not commit that stamp. The deb
version is
`X.Y.Z~dev<YYYYMMDD>.<run_id>.<run_attempt>+g<sha>`. CI strips a Debian
revision before adding 1 to the patch, so `2.4.12-1` yields
`2.4.13~dev<YYYYMMDD>.<run_id>.<run_attempt>+g<sha>`. CI uploads that `.deb`
to Packagecloud `wlanpi/dev` and does not tag it. In the built package,
`wlanpi_core/__version__.py` is `X.Y.Z.dev<YYYYMMDD>` per
[PEP 440](https://www.python.org/dev/peps/pep-0440/).

A release pull request sets the changelog with `dch -v <version>` and no
Debian revision, then `dch -r ""`. Set `wlanpi_core/__version__.py` to that
same `major.minor.patch`. The version check fails if they diverge. On a
changelog that still says `2.4.12-1`, `dch -i` writes `2.4.12-2`. Do not use
`dch -i`.

When that stamping is live, CI uploads the release to `wlanpi/main` and tags
`v<version>`. Do not create that tag by hand. Until then, a changelog edit
on `main` still uploads to `wlanpi/dev`. Do not edit the changelog to publish
a fix.

Before you merge a release, confirm that the OpenAPI Reference Check passes.
If it fails, run `tox -e openapi` and commit `docs/openapi.json` in that
same pull request.

Follow [Land a Fix and Cut a Release](https://github.com/WLAN-Pi/developers/blob/main/RELEASING.md).

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
- [Land a Fix and Cut a Release](https://github.com/WLAN-Pi/developers/blob/main/RELEASING.md) - Fix, dev build, and release procedure
- [PACKAGING.md](PACKAGING.md) - Packaging standards for this repo
- [Gunicorn settings documentation](https://gunicorn.org/reference/settings/#debugging)
