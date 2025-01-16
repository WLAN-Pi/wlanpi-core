#!/bin/bash
for file in $(find wlanpi_core -type f -name "*.py"); do
    sed 's/[[:space:]]*$//' "$file" | cat -A | diff --color=always - <(cat -A "$file")
done