#!/bin/bash
find wlanpi_core -type f -name "*.py" -exec sed -i 's/[[:space:]]*$//' {} +