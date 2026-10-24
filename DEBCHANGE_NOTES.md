
# Tips for Working with debchange

## debchange - a tool for maintaining the source package changelog file

While you could edit the changelog directly, it is recommended to use `debchange` or its alias `dch` to assist in the modification of the changelog.

If you are regularly using debchange, it is also a good idea to set environment variables on your development machine. 

If you do not, when `debchange` is invoked, it will automatically author the change with `<user@systemname>` when you should use the `Dale Cooper <special_agent@twinpeaks.com>` format.

## debchange - usage tips

### Release entry

A fix or feature pull request does not edit `debian/changelog`. Only a release pull request does. From the repository root, run `dch -v <version>` with no Debian revision, then `dch -r ""`. Do not run `dch -i`. On `2.4.12-1`, `dch -i` writes `2.4.12-2`.

To edit the current entry without a new version, run `dch -e`.

## debchange - versions

On version numbers, from the Debian maintainers guide:

> One tricky case can occur when you make a local package, to experiment with the packaging before uploading the normal version to the official archive, e.g., 1.0.1-1. For smoother upgrades, it is a good idea to create a changelog entry with a version string such as 1.0.1-1~rc1. You may unclutter changelog by consolidating such local change entries into a single entry for the official package.

Do not add that local revision on a fix. The release pull request sets the version.

## debchange - environment variables

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

## debchange - additional reading

For more information on debchange review the manpages by running `man debchange` from your terminal.

Additionally review the [Debian maintainers guide Chapter 8](https://www.debian.org/doc/manuals/maint-guide/update.en.html).
