#!/bin/bash
# unlink our symlinks if they exist

function unlink_if_existing() {
    if [ -L "$1" ]; then
        unlink $1
    fi
}

unlink_if_existing /etc/nginx/sites-enabled/wlanpi_core.conf
unlink_if_existing /etc/nginx/sites-enabled/wlanpi_core_tls.conf
unlink_if_existing /etc/nginx/sites-enabled/wlanpi_mcp_tls.conf
