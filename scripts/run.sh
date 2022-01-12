#!/usr/bin/env bash

set -x

uvicorn wlanpi_core.app:create_app --reload --port 8000 --host 0.0.0.0