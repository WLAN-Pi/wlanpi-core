# Development Workflow

Table of contents:

* [Development Workflow](#development-workflow)
  * [Releases](#releases)
  * [Server setup](#server-setup)
  * [Third Party Depends](#third-party-depends)
  * [Setup development environment](#setup-development-environment)
  * [Developing](#developing)
  * [Troubleshooting](#troubleshooting)
  * [Tagging](#tagging)
  * [`debian/changelog`](#`debian/changelog`)
  * [Versioning](#versioning)
  * [Commiting](#commiting)
    * [Linting and formatting](#linting-and-formatting)
    * [Testing](#testing)
  * [Building the Debian Package](#building-the-debian-package)

## Releases

Each release should contain appropriate git tagging and versioning.

CI/CD will be setup and triggered by pushes to `{repo}/debian/changelog`.

So, this meaning you should have some hope that your hotfix or feature works as intended. It would be a good idea to format, lint, and test the code at this stage.

Thus, you should not make changes to the `changelog` until you are ready to deploy.

## Server setup

Install depends:

```
sudo apt update 
sudo apt-get install -y -q build-essential git unzip zip nload tree ufw dbus pkg-config gcc libpq-dev libdbus-glib-1-dev libglib2.0-dev libcairo2-dev libgirepository1.0-dev libffi-dev cmake vlan libdbus-1-dev
sudo apt-get install -y -q python3-pip python3-dev python3-venv python3-wheel
```

Setup ufw (if not done already for you):

```
ufw allow 22
ufw allow 80
ufw allow 8000
ufw allow 31415
ufw enable
```

## Setup development environment

1. Clone repo
2. Create virtualenv
3. Install wheel and setuptools in virtualenv
4. Install package into virtualenv with extras

```
git clone git@github.com:WLAN-Pi/wlanpi-core.git 
cd wlanpi-core
python3 -m venv venv && source venv/bin/activate
pip install -U pip pip-tools wheel setuptools 

# normal users who do not need to run or create tests
pip install .

# developers install test depends like so
pip install .[testing]
```

## Developing

Once you've 1) setup the virtualenv and installed Python requirements, and 2) setup OS and package requirements, you can start developing by running wlanpi_core directly. There are two options:

1. `WLANPI_LOG_LEVEL=DEBUG sudo -E venv/bin/python -m wlanpi_core --reload` from the root of the repo:

```
$ WLANPI_LOG_LEVEL=DEBUG sudo -E venv/bin/python -m wlanpi_core 
Consider running with --reload for live reload as you iterate on hotfixes or features...

2025-01-14 00:55:23,729 - root - INFO - Logging configured at DEBUG level
2025-01-14 00:55:23,731 - wlanpi_core.app - INFO - Logging configuration started
2025-01-14 00:55:23,731 - wlanpi_core.app - DEBUG - Debug level logging
INFO:     Started server process [77189]
INFO:     Waiting for application startup.
2025-01-14 00:55:23,904 - wlanpi_core.core.security - DEBUG - Secured secrets directory: /opt/wlanpi-core/.secrets
2025-01-14 00:55:23,905 - wlanpi_core.core.security - INFO - Loaded existing shared secret
2025-01-14 00:55:23,905 - wlanpi_core.core.security - INFO - Loaded existing encryption key
2025-01-14 00:55:23,906 - wlanpi_core.core.security - INFO - Security initialization complete
2025-01-14 00:55:23,907 - wlanpi_core.core.database - DEBUG - Starting database integrity check
2025-01-14 00:55:23,911 - wlanpi_core.core.database - DEBUG - Created new connection for thread 548160708672
2025-01-14 00:55:23,912 - wlanpi_core.core.database - DEBUG - Starting database initialization
2025-01-14 00:55:23,912 - wlanpi_core.core.database - DEBUG - Starting database integrity check
2025-01-14 00:55:23,914 - wlanpi_core.core.database - DEBUG - Database initialization complete
2025-01-14 00:55:23,915 - wlanpi_core.app - INFO - Database manager initialization complete
2025-01-14 00:55:23,915 - wlanpi_core.app - INFO - Retention manager initialization complete
2025-01-14 00:55:23,916 - wlanpi_core.core.database - DEBUG - Database connection verified
2025-01-14 00:55:23,916 - wlanpi_core.core.database - DEBUG - Reusing existing connection
2025-01-14 00:55:23,917 - wlanpi_core.core.auth - INFO - Current signing_keys count: 2
2025-01-14 00:55:23,917 - wlanpi_core.core.auth - INFO - Found key: id=2, created=1736739278, active=1
2025-01-14 00:55:23,918 - wlanpi_core.core.auth - INFO - Found key: id=1, created=1736739244, active=0
2025-01-14 00:55:23,918 - wlanpi_core.core.auth - INFO - Fetching active key from database
2025-01-14 00:55:23,924 - wlanpi_core.core.auth - INFO - Retrieved existing key_id 2 created at 1736739278
2025-01-14 00:55:23,925 - wlanpi_core.app - INFO - Token manager initialization complete
2025-01-14 00:55:23,925 - wlanpi_core.app - INFO - Activity manager initialization complete
2025-01-14 00:55:23,926 - wlanpi_core.core.database - DEBUG - Database connection invalid
2025-01-14 00:55:23,927 - wlanpi_core.core.database - DEBUG - Database connection invalid
2025-01-14 00:55:23,927 - wlanpi_core.core.database - DEBUG - Closed invalid connection
2025-01-14 00:55:23,928 - wlanpi_core.core.database - DEBUG - Starting database integrity check
2025-01-14 00:55:23,932 - wlanpi_core.core.database - DEBUG - Created new connection for thread 548160708672
2025-01-14 00:55:23,933 - wlanpi_core.core.database - INFO - Ran clean up data older than 1 days
2025-01-14 00:55:23,933 - wlanpi_core.core.database - DEBUG - Checked database size
2025-01-14 00:55:23,934 - wlanpi_core.core.database - DEBUG - Starting database backup
2025-01-14 00:55:23,934 - wlanpi_core.core.database - DEBUG - Starting database integrity check
2025-01-14 00:55:23,937 - wlanpi_core.core.database - DEBUG - Database connection verified
2025-01-14 00:55:23,937 - wlanpi_core.core.database - DEBUG - Reusing existing connection
2025-01-14 00:55:23,960 - wlanpi_core.core.database - DEBUG - Database backup completed
2025-01-14 00:55:23,967 - wlanpi_core.core.database - DEBUG - Database connection verified
2025-01-14 00:55:23,968 - wlanpi_core.core.database - DEBUG - Reusing existing connection
2025-01-14 00:55:23,969 - wlanpi_core.core.auth - DEBUG - Before purge - Total: 5, Expired: 0, Revoked: 0
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

If you are running directly, now you can open your browser and interact with these URLs:

- API frontend, with routes handled based on the path: http://localhost:8000

- Automatic interactive documentation with Swagger UI (from the OpenAPI backend): http://localhost:8000/documentation

- ReDoc has been disabled with `redoc_url=None` in app.py ~~Alternative automatic documentation with ReDoc (from the OpenAPI backend): http://localhost:8000/redoc~~

## creating JWT token from localhost

```
canonical_string="POST\n/api/v1/auth/token\n{\"device_id\": \"testing\"}"
signature=$(printf "$canonical_string" | openssl dgst -sha256 -hmac "$(cat /opt/wlanpi-core/.secrets/shared_secret)" -binary | xxd -p -c 256)

curl -X 'POST' \
  -H "X-Request-Signature: $signature" \
  'localhost:31415/api/v1/auth/token' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{"device_id": "testing"}'
```

## apitest.sh

```
./apitest.sh -X POST -e /auth/token -P '{"device_id": "testing"}'
./apitest.sh -e /system/device/model
```

### Ports

In production, the port is :31415.

In developement, the default port is :8000, but you can change this with `--port <port>` argument.

### Running your development version in place (method 1)

Doing some development on the backend and want run your version in place instead of a different port? Use this trick to start it the way it's started in `debian/wlanpi-core.service`.

Change the workingdirectory symlink.

Verify where to restore before modifying with `ls -l /opt/wlanpi-core/workingdirectory`:

```
(venv) wlanpi@wlanpi-573:~ $ ls -l /opt/wlanpi-core/workingdirectory
lrwxrwxrwx 1 root root 56 Jan 13 13:36 /opt/wlanpi-core/workingdirectory -> /opt/wlanpi-core/lib/python3.9/site-packages/wlanpi_core
```

Link to your development location:

```
sudo ln -sfn /home/wlanpi/wlanpi-core/wlanpi_core /opt/wlanpi-core/workingdirectory
```

Reboot service:

```
sudo systemctl restart wlanpi-core.service
sudo systemctl status wlanpi-core.service
```

Do things.

Done? Restore and reboot services.

```
sudo ln -sfn /opt/wlanpi-core/lib/python3.9/site-packages/wlanpi_core /opt/wlanpi-core/workingdirectory
```

### Running your development version in place (method 2)

Doing some development on the backend and want run your version in place instead of a different port? Use this trick to start it the way it's started in `debian/wlanpi-core.service`.

1. Starting in your repo root, elevate to root and activate the repo venv:
    ```
    sudo su --
    source venv/bin/activate
    ``` 
2. Stop the installed wlanpi-core and socket, so that it won't auto-restart the built-in core:
    ```
    systemctl stop wlanpi-core.service && systemctl stop wlanpi-core.socket
    ```
3. Start your development copy in its place (`--bind` binds a unix socket to where the service would, allowing nginx to proxy to your copy correctly)  :
    ```
    gunicorn --workers 1 --reload -k uvicorn.workers.UvicornWorker --bind unix:/run/wlanpi_core.sock wlanpi_core.asgi:app
    ```
4. If you want to access the API directly:
    1. You may need to first open the port in the firewall. You should probably only do this on a safe, trusted network.
       ```
       ufw allow 31415
       ```
    2. Now you can go to `http://wlanpi-###.local:31415/` or `http://<ip>:31415/`
5. Occasionally, changes may not get picked up as reloads happen. If so, either restart the process or send a HUP with `kill -HUP <gunicorn PID>`.
6. When you're done, restart the original core services:
    ```
    systemctl stop wlanpi-core.socket && systemctl stop wlanpi-core.service
    ```

For more information on the debug options gunicorn provides, including how to watch extra files for reloading, check the [Gunicorn settings documentation](https://docs.gunicorn.org/en/stable/settings.html#debugging).

## Troubleshooting

Problems with the unit file? Check out the journal for the service:

```
journalctl -u wlanpi-core
```

Follow with:

```
journalctl --follow --unit wlanpi-core
journalctl -f -b -u wlanpi-core
journalctl -f -n 10 -u wlanpi-core
```

Check last 20 lines and then follow the logs

```
tail -n 20 -f /var/log/wlanpi_core/app.log
tail -n 20 -f /var/log/wlanpi_core/debug/debug.log
```

## tmpfs debugging

```
systemctl status var-log-wlanpi_core-debug.mount
mount | grep wlanpi_core/debug
df -h /var/log/wlanpi_core/debug
ls -la /var/log/wlanpi_core/debug
```

Example:

```
$ systemctl status var-log-wlanpi_core-debug.mount
● var-log-wlanpi_core-debug.mount - Debug log tmpfs mount for wlanpi-core
     Loaded: loaded (/lib/systemd/system/var-log-wlanpi_core-debug.mount; enabled; vendor preset: enabled)
     Active: active (mounted) since Tue 2025-01-14 09:25:03 CST; 2min 44s ago
      Where: /var/log/wlanpi_core/debug
       What: tmpfs
      Tasks: 0 (limit: 1655)
        CPU: 5ms
     CGroup: /system.slice/var-log-wlanpi_core-debug.mount

Jan 14 09:25:03 wlanpi-573 systemd[1]: Mounting Debug log tmpfs mount for wlanpi-core...
Jan 14 09:25:03 wlanpi-573 systemd[1]: Mounted Debug log tmpfs mount for wlanpi-core.

$ mount | grep wlanpi_core/debug
tmpfs on /var/log/wlanpi_core/debug type tmpfs (rw,relatime,size=25600k,mode=750,uid=1000)

$ df -h /var/log/wlanpi_core/debug
Filesystem      Size  Used Avail Use% Mounted on
tmpfs            25M   12K   25M   1% /var/log/wlanpi_core/debug

$ ls -la /var/log/wlanpi_core/debug
total 16
drwxr-x--- 2 wlanpi root   60 Jan 14 09:25 .
drwxr-xr-x 3 root   root 4096 Jan 14 09:25 ..
-rw-r--r-- 1 root   root 8249 Jan 14 09:25 debug.log
```

## Tagging

Each release should have a git tag.

Example: `git tag v1.2.3 -m "Release 1.2.3"`, in which case `v1.2.3` is a tag name and the semantic version is `1.2.3`.

Use `git push origin <tag_name>` to push your local tag to the remote repository (Github).

## `debian/changelog`

Create a changelog entry for a new release: `dch -i`

Describe what you changed, fixed, or enhanced.

If you were to do this initially, and create the changelog file, you can create it by browsing to the root of the repository, and running `debchange --create`. This will be already done by the time you read this.

See [DEBCHANGE_NOTES.md](DEBCHANGE_NOTES.md) for further reading.

## Versioning

Each release requires versions to be updated in __two__ locations:

1. debian changelog: `{repo}/debian/changelog` via `debchange`

2. python package: `{repo}/wlanpi_core/__version__.py` via manual update.

Please note that Python package versioning should follow PEP 440. https://www.python.org/dev/peps/pep-0440/

## Commiting

Before committing, please lint, format, and test your code with tox.

0. `tox -e format`
0. `tox -e lint`
0. `tox -e test`

### Linting and formatting

You should install depends with `pip install .[testing]` and then you will be able to run `tox -e format` and `tox -e lint` to format and lint respectively.

`tox` will automatically run a few tools such as black, flake8, and isort in a consistent manner. 

### Testing

You should install depends with `pip install .[testing]` and then you will be able to run `tox` to run tests.

## Building the Debian Package

From the root directory of this repository run:

```
dpkg-buildpackage -us -uc -b
```

See [PACKAGING.md](PACKAGING.md) for further reading.
