# Debian Packaging Instructions for wlanpi-core

We're using spotify's opensurce dh-virtualenv to provide debian packaging and deployment of our Python code inside a virtualenv.

dh-virtualenv is essentially a wrapper or a set of extensions around existing debian tooling. You can find the official page [here](https://github.com/spotify/dh-virtualenv).

Our goal is to use dh-virtualenv for accomplishing things like packaging, symlinks, installing configuration files, systemd service installation, and virtualization at deployment.

## Getting Started

On your _build host_, install the build tools (these are only needed on your build host):

```
sudo apt-get install build-essential debhelper devscripts equivs python3-pip python3-all python3-dev python3-setuptools dh-virtualenv
```

Install Python depends:

```
python3 -m pip install mock
```

This is required, otherwise the tooling will fail when tries to evaluate which tests to run.

## Building our project

From the root directory of this repository run:

```
dpkg-buildpackage -us -uc -b
```

If you are found favorable by the packaging gods, you should see some output files at `../wlanpi-core` like this:

```
...
```

## sudo apt remove vs sudo apt purge

If we remove our package, it will leave behind the config file in `/etc`:

`sudo apt remove wlanpi-core`

If we want to clean `/etc` we should purge:

`sudo apt purge wlanpi-core`


## installing our deb with apt for testing

```
...
```

## APPENDIX

### Build dependencies

If you don't want to satisfy build dependencies:

```
dpkg-buildpackage -us -uc -b -d
```

### Debian Packaging Breakdown

- `changelog`: Contains changelog information and sets the version of the package. date must be in RFC 5322 format.
- `control`: provides dependencies, package name, and other package meta data. tols like apt uses these to build dependencies, etc.
- `copyright`: copyright information for upstream source and packaging
- `compat`: sets compatibility level for debhelper
- `rules`: this is the build recipe for make. it does the work for creating our package. it is a makefile with targets to compile and install the application, then create the .deb file.
- `wlanpi-core.service`: `dh` automatically picks up and installs this systemd service
- `wlanpi-core.triggers`: tells dpkg what packages we're interested in

### Installing dh-virtualenv from source

Some OS repositories have packages already. 

```
sudo apt install dh-virtualenv
```

If not available, you can build it from source:

```
cd ~

# Install needed packages
sudo apt-get install devscripts python3-virtualenv python3-sphinx \
                     python3-sphinx-rtd-theme git equivs
# Clone git repository
git clone https://github.com/spotify/dh-virtualenv.git
# Change into working directory
cd dh-virtualenv
# This will install build dependencies
sudo mk-build-deps -ri
# Build the *dh-virtualenv* package
dpkg-buildpackage -us -uc -b

# And finally, install it (you might have to solve some
# dependencies when doing this)
sudo dpkg -i ../dh-virtualenv_<version>.deb
```