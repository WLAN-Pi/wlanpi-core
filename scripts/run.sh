#!/usr/bin/env bash

set -x

uvicorn wlanpi_core.app:app --reload --env-file .env  --port 8000 --host 0.0.0.0