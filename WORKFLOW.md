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
sudo apt-get install -y -q build-essential git unzip zip nload tree ufw dbus pkg-config gcc libpq-dev libdbus-glib-1-dev libglib2.0-dev libcairo2-dev libgirepository1.0-dev libffi-dev cmake vlan 
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

1. `python -m wlanpi_core --reload` from the root of the repo:

```
(venv) wlanpi@rbpi4b-8gb:[~/dev/wlanpi-core]: python -m wlanpi_core --reload
WARNING!!! Starting wlanpi-core directly with uvicorn. This is typically for development. Are you sure? (y/n): y
INFO:     Will watch for changes in these directories: ['/home/wlanpi/dev/wlanpi-core']
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [25475] using statreload
INFO:     Started server process [25494]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

2. Or use `scripts/run.sh`:

```
cd {repo}
./scripts/run.sh 
```

output should look like:

```
(venv) wlanpi@rbpi4b-8gb:[~/dev/wlanpi-core]: ./scripts/run.sh 
INFO:     Will watch for changes in these directories: ['/home/wlanpi/dev/wlanpi-core']
INFO:     Loading environment from '.env'
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [25969] using statreload
INFO:     Started server process [25971]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

You may need to make scripts executable prior to first run.

```
chmod +x ./scripts/run.sh 
```

If you are running directly, now you can open your browser and interact with these URLs:

- API frontend, with routes handled based on the path: http://localhost:8000

- Automatic interactive documentation with Swagger UI (from the OpenAPI backend): http://localhost:8000/documentation

- ReDoc has been disabled with `redoc_url=None` in app.py ~~Alternative automatic documentation with ReDoc (from the OpenAPI backend): http://localhost:8000/redoc~~

In production, the port will be different.

### Protip

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
    2. Now you can go to http://wlanpi-###.local:31415/ 
5. Occasionally, changes may not get picked up as reloads happen. If so, either restart the process or send a HUP with `kill -HUP <gunicorn PID>`.
6. When you're done, restart the original core services:
    ```
    systemctl stop wlanpi-core.socket && systemctl stop wlanpi-core.service
    ```

For more information on the debug options gunicorn provides, including how to watch extra files for reloading, check the [Gunicorn settings documentation](https://docs.gunicorn.org/en/stable/settings.html#debugging).

## Debugging while developing or running

### Add debugging

Pick one of the two options below:

Set the variable and then preserve the environment when running like `sudo -E`:

```
export WLANPI_CORE_DEBUGGING=1
sudo -E venv/bin/python -m wlanpi_core
```

Set the environment variable while running as sudo:

```
sudo WLANPI_CORE_DEBUGGING=1 venv/bin/python -m wlanpi_core
```

To stop debugging:

```
unset WLANPI_CORE_DEBUGGING
```

## Troubleshooting

Problems with the unit file? Check out the journal for the service:

```
journalctl -u wlanpi-core
```

## Tagging

Each release version should have a git tag.

Example: `git tag v1.2.3 -m "Release version 1.2.3"`, in which case `v1.2.3` is a tag name and the semantic version is `1.2.3`.

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

Before committing, please lint, format, and test your code.

### Linting and formatting

You should install depends with `pip install .[testing]` and then you will be able to run `tox -e format` and `tox -e lint` to format and lint respectively.

For reference, there are `format.sh`, `lint.sh`, and `test.sh` scripts found in `{repo}/scripts`.

Here are some of the tools used:

* autoflake
* black
* flake8
* isort
* mypy

### Testing

You should install depends with `pip install .[testing]` and then you will be able to run `tox` to run tests.

## Building the Debian Package

From the root directory of this repository run:

```
dpkg-buildpackage -us -uc -b
```

See [PACKAGING.md](PACKAGING.md) for further reading.
