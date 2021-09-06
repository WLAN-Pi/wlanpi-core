# Development Workflow

## Releases

Each release should contain appropriate git tagging and versioning.

CI/CD will be setup and triggered by pushes to `{repo}/debian/changelog`.

Thus, you should not make changed to the `changelog` until you are ready to deploy.

Meaning you should have relative confidence that your hotfix or feature works as intended. You should review linting and testing at this stage.

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

6. `python3 -m wlanpi_core --reload` should start the app using uvicorn with live reload. or:

    ```
    cd {repo}
    ./scripts/run.sh 
    ```

You may need to make scripts executable prior to first run.

```
sudo chmod +x ./scripts/run.sh 
```

Now you can open your browser and interact with these URLs:

- Frontend, with routes handled based on the path: http://localhost

- Backend, OpenAPI based JSON based web API: http://localhost/api/

- Automatic interactive documentation with Swagger UI (from the OpenAPI backend): http://localhost/docs

- Alternative automatic documentation with ReDoc (from the OpenAPI backend): http://localhost/redoc

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

## Versioning

Each release requires versions to be updated in __two__ locations:

1. debian changelog: `{repo}/debian/changelog` via `debchange`

2. python package: `{repo}/wlanpi_core/__version__.py` via manual update.

Please note that PEP 440 is applicable with Python package versioning. https://www.python.org/dev/peps/pep-0440/

## Commiting

Before committing, please lint, format, and test your code. Here are some of the projects used:

- autoflake
- black
- flake8
- isort
- mypy

## Linting and formatting

Please use the `format.sh`, `lint.sh`, and `test.sh` scripts found in `{repo}/scripts`.

## Testing

It is preferred to use `tox` in your test environment.

## Manual Build

From the root directory of this repository run:

```
dpkg-buildpackage -us -uc -b
```

See [PACKAGING.md](PACKAGING.md) for more.

## debchange tips

### debchange - tool for maintaining the source package changelog file

It is recommended to use `debchange` or its alias `dch` to assist in the modification of the changelog. You should 

If you are using debchange, it is a good idea to set environment variables on your development machine. If you do not, when `debchange` is invoked, it will automatically author the change with `<user@systemname>` when you should use the `Dale Cooper <special_agent@twinpeaks.com>` format. 

### debchange - usage

#### Create a new version entry

You can run debchange from the root of the repository as debchange will climb the directory tree until it finds a `debian/changelog` file.

```
(venv) wlanpi@rbpi4b-8gb:[~/dev/wlanpi-core]: debchange
```

#### Update an existing version entry

You should minially use `dch -i` when adding a new changelog because `-i` increases the release number and adds a changelog entry.

If you want to edit the changelog without changing the version or adding a new entry, use `-e` instead of `-i`.

### debchange - versions

On version numbers, from the Debian maintainers guide:

> One tricky case can occur when you make a local package, to experiment with the packaging before uploading the normal version to the official archive, e.g., 1.0.1-1. For smoother upgrades, it is a good idea to create a changelog entry with a version string such as 1.0.1-1~rc1. You may unclutter changelog by consolidating such local change entries into a single entry for the official package.

### debchange - environment variables

You will likely want to set the `DEBFULLNAME` and `DEBEMAIL` environment variables on your development system. Two options demonstrated:

Set per session:

```bash
(venv) wlanpi@rbpi4b-8gb:[~/dev/wlanpi-core]: export DEBFULLNAME="Josh Schmelzle"
(venv) wlanpi@rbpi4b-8gb:[~/dev/wlanpi-core]: export DEBEMAIL="Josh Schmelzle <josh@joshschmelzle.com>"
```

Set to take effect at shell login via `~/.profile`


```bash
# vim ~/.profile
# append the following:
export DEBFULLNAME="Josh Schmelzle"
export DEBEMAIL="Josh Schmelzle <josh@joshschmelzle.com>"
```

### debchange - review

For more information on debchange review the manpages by running `man debchange` from your terminal.

Additionally review the [Debian maintainers guide Chapter 8](https://www.debian.org/doc/manuals/maint-guide/update.en.html).