#!/bin/bash

RULES_DIR="/etc/wlanpi-core/ufw"
CURRENT_VERSION_FILE="${RULES_DIR}/current-rules-version"
INSTALLED_VERSION_FILE="/etc/wlanpi-core/installed-rules-version"

set -e

apply_ufw_rules() {
    if [ ! -f "$CURRENT_VERSION" ]; then
        echo "No rules version found."
        return 1
    fi

    CURRENT_VERSION=$(cat "$CURRENT_VERSION_FILE")

    if [ -f "$INSTALLED_VERSION" ]; then
        INSTALLED_VERSION=$(cat "$INSTALLED_VERSION_FILE")
        if [ "$CURRENT_VERSION" == "$INSTALLED_VERSION" ]; then
            echo "ufw rules are up to date."
            return 0
        fi
    fi

    if ! command -v ufw >/dev/null 2>&1; then
        echo "ufw is not installed. skipping rule application."
        return 0
    fi

    if ! ufw status | grep -q "Status: active"; then
        echo "enabling ufw..."
        ufw enable
    fi

    if [ -f "${RULES_DIR}/wlanpi-core.rules" ]; then
        cp "${RULES_DIR}/wlanpi-core.rules" /etc/ufw/applications.d/wlanpi-core
    else
        echo "warning: wlanpi-core ufw rules file not found." >&2
        return 1
    fi

    ufw allow wlanpi-core
    ufw allow wlanpi-webui
    ufw reload


    cp "$CURRENT_VERSION" "$INSTALLED_VERSION_FILE"
    echo "ufw rules applied successfully."
}

if ! apply_ufw_rules; then
    echo "Failed to apply UFW rules completely." >&2
    exit 1
fi

exit 0