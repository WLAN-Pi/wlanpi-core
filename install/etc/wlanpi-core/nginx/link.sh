#!/bin/bash

function isValidSymlink() {
    if [ -L "$1" ]; then
        return 0
    else
        return 1
    fi
}

WLANPI_CORE=/etc/nginx/sites-enabled/wlanpi_webui.conf

if ! isValidSymlink $WLANPI_CORE; then
    echo "Linking wlanpi_core.conf..."
    ln -s /etc/wlanpi-core/nginx/sites-enabled/wlanpi_core.conf $WLANPI_CORE
fi

echo "Restarting nginx..."

systemctl restart nginx.service