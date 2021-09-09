# Development Workflow

## Releases

Each release should contain appropriate git tagging and versioning.

CI/CD will be setup and triggered by pushes to `{repo}/debian/changelog`.

So, this meaning you should have some hope that your hotfix or feature works as intended. It would be a good idea to format, lint, and test the code at this stage.

Thus, you should not make changes to the `changelog` until you are ready to deploy.

## Server setup

Install depends:

```
sudo apt update 
sudo apt-get install -y -q build-essential git unzip zip nload tree ufw dbus pkg-config gcc libpq-dev libdbus-glib-1-dev
sudo apt-get install -y -q python3-pip python3-dev python3-venv python3-wheel
```

Setup ufw (if not done already for you):

```
ufw allow 22
ufw allow 80
ufw allow 8000
ufw enable
```

## Third Party Depends

TODO: clarify why this is here.

- dbus-python
- uvicorn 
- python-dotenv
- fastapi
- psutil

## Setup development environment

1. Clone repo and `cd` into repo folder.
2. Create a new virtualenv with `python3 -m venv venv`
3. Activate the virtualenv with `source venv/bin/activate`
4. Update pip, setuptools, and wheel with `pip install -U pip wheel setuptools`
5. Install requirements with `pip install -r requirements`

or

- Create virtualenv and install dependencies.

    ```
    cd {repo}/wlanpi-core
    python3 -m venv venv && source ./venv/bin/activate
    python -m pip install -U pip wheel setuptools
    pip install -r requirements.txt
    ```

- Activate the virtualenv

    ```
    cd {repo}
    source ./venv/bin/activate
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

Now you can open your browser and interact with these URLs:

- Frontend, with routes handled based on the path: http://localhost:8000

- Backend, OpenAPI based JSON based web API: http://localhost:8000/api/

- Automatic interactive documentation with Swagger UI (from the OpenAPI backend): http://localhost:8000/docs

- Alternative automatic documentation with ReDoc (from the OpenAPI backend): http://localhost:8000/redoc

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

1. (optional) Create the changelog file, this will be created already by the time you are reading this, but you can create it by browsing to the root of the repository, and running `debchange --create`.

2. Run `debchange` to create a new changelog entry, describe what you changed, fixed, or enhanced.

See [DEBCHANGE_NOTES.md](DEBCHANGE_NOTES.md) for further reading.

## Versioning

Each release requires versions to be updated in __two__ locations:

1. debian changelog: `{repo}/debian/changelog` via `debchange`

2. python package: `{repo}/wlanpi_core/__version__.py` via manual update.

Please note that Python package versioning should follow PEP 440. https://www.python.org/dev/peps/pep-0440/

## Commiting

Before committing, please lint, format, and test your code.

### Linting and formatting

Please use the `format.sh`, `lint.sh`, and `test.sh` scripts found in `{repo}/scripts`.

Here are some of the tools used:

- autoflake
- black
- flake8
- isort
- mypy

TODO: migrate to `tox` for formatting and linting.

### Testing

TODO: setup `tox` with pytest for unit testing.

## Building the Debian Package

From the root directory of this repository run:

```
dpkg-buildpackage -us -uc -b
```

See [PACKAGING.md](PACKAGING.md) for further reading.
