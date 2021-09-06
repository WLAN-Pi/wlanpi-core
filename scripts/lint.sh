#!/usr/bin/env bash

set -x

mypy wlanpi_core
black wlanpi_core --check
isort --check-only wlanpi_core
flake8 wlanpi_core