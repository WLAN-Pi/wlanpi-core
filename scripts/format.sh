#!/usr/bin/env bash

set -x

autoflake --remove-all-unused-imports --recursive --remove-unused-variables --in-place wlanpi_core --exclude=__init__.py
black wlanpi_core
isort wlanpi_core --recursive --diff