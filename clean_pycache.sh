#!/bin/bash
# clean pycache
find . -regex '^.*\(__pycache__\|\.py[co]\)$' -delete
