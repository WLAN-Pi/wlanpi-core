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
dpkg-deb: building package 'wlanpi-core-dbgsym' in '../wlanpi-core-dbgsym_0.0.1~rc1_arm64.deb'.
dpkg-deb: building package 'wlanpi-core' in '../wlanpi-core_0.0.1~rc1_arm64.deb'.
 dpkg-genbuildinfo --build=binary
 dpkg-genchanges --build=binary >../wlanpi-core_0.0.1~rc1_arm64.changes
dpkg-genchanges: info: binary-only upload (no source code included)
 dpkg-source --after-build .
dpkg-buildpackage: info: binary-only upload (no source included)
(venv) wlanpi@rbpi4b-8gb:[~/dev/wlanpi-core]: ls .. | grep wlanpi-core_
wlanpi-core_0.0.1~rc1_arm64.buildinfo
wlanpi-core_0.0.1~rc1_arm64.changes
wlanpi-core_0.0.1~rc1_arm64.deb
```

## sudo apt remove vs sudo apt purge

If we remove our package, it will leave behind the config file in `/etc`:

`sudo apt remove wlanpi-core`

If we want to clean `/etc` we should purge:

`sudo apt purge wlanpi-core`


## installing our deb with apt for testing

```
(venv) wlanpi@rbpi4b-8gb:[~/dev]: sudo dpkg -i wlanpi-core_0.0.1~rc1_arm64.deb 
Selecting previously unselected package wlanpi-core.
(Reading database ... 80780 files and directories currently installed.)
Preparing to unpack wlanpi-core_0.0.1~rc1_arm64.deb ...
Unpacking wlanpi-core (0.0.1~rc1) ...
Setting up wlanpi-core (0.0.1~rc1) ...
Created symlink /etc/systemd/system/multi-user.target.wants/wlanpi-core.service → /lib/systemd/system/wlanpi-core.service.
Created symlink /etc/systemd/system/sockets.target.wants/wlanpi-core.socket → /lib/systemd/system/wlanpi-core.socket.
Job for wlanpi-core.service failed because the control process exited with error code.
See "systemctl status wlanpi-core.service" and "journalctl -xe" for details.
Linking our nginx.conf config to /etc/nginx/nginx.conf ...
Linking our wlanpi_core.conf to sites-enabled ...
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
User wlanpi_api does not exist, creating ...
User wlanpi_api created ...
random password assigned to wlanpi_api
Fix up permissions on /var/log/wlanpi-core/ for wlanpi_api ...
/var/log/wlanpi-core/access.log does not exist, creating it ...
/var/log/wlanpi-core/error.log does not exist, creating it ...
Restarting wlanpi-core.service ...
Processing triggers for man-db (2.8.5-2) ...
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

### Maintainer Scripts

- `postinst` - this runs after the install and handles setting up a few things.
- `postrm` - this runs and handles `remove` and `purge` args when uninstalling or purging the package.

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
