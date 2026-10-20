#!/bin/bash
# clean_pycache.sh: delete __pycache__ dirs and .pyc/.pyo files under ../ (run from scripts/)
find ../. -regex '^.*\(__pycache__\|\.py[co]\)$' -delete
