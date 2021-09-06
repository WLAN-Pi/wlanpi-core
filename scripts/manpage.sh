#!/bin/sh
echo >&2 "Generating man page using pandoc"
pandoc -s -f markdown-smart -t man ../debian/wlanpi-core.1.md -o ../debian/wlanpi-core.1 || exit
echo >&2 "Done. You can read it with:   man ./debian/wlanpi-core.1"