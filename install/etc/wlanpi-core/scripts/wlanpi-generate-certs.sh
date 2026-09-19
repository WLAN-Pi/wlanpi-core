#!/bin/bash
#
# Generate the per-device self-signed TLS certificates used by nginx,
# wlanpi-webui, cockpit, and grafana.
#
# A key baked into an image would be shared by every device flashed from it,
# so generation happens on the device (first real boot or package postinst).
# The certificate must cover the .local hostname that
# wlanpi-rename-at-startup assigns (wlanpi-<last-3-chars-of-eth0-mac>.local),
# otherwise browsers/users hit hostname mismatch warnings (wlanpi-core#175).
# Existing certificates that predate that SAN are regenerated.
#
# A hostname changed by any other means (not the eth0-MAC-derived name above)
# is not tracked, so the certificate is not regenerated for it. Clients that
# connect by such a name get a hostname mismatch.
#
# Test hooks: NGINX_SSL_DIR, COCKPIT_CERTS_DIR and WLANPI_ETH0_MAC override
# the production paths/MAC so the script can be exercised without touching
# the live system.

set -euo pipefail

NGINX_SSL_DIR=${NGINX_SSL_DIR:-/etc/nginx/ssl}
COCKPIT_CERTS_DIR=${COCKPIT_CERTS_DIR:-/etc/cockpit/ws-certs.d}
CERT=$NGINX_SSL_DIR/self-signed-wlanpi.cert
KEY=$NGINX_SSL_DIR/self-signed-wlanpi.key

# The hostname wlanpi-rename-at-startup.sh assigns: wlanpi-<last 3 chars of
# eth0 MAC>. Empty if eth0 is absent, in which case we cannot know it.
expected_hostname() {
    local mac last3
    mac=${WLANPI_ETH0_MAC:-$(sed 's/://g' /sys/class/net/eth0/address 2>/dev/null || true)}
    mac=${mac//:/}
    last3=${mac: -3}
    if [ ${#last3} -eq 3 ]; then
        echo "wlanpi-${last3}"
    fi
}

# Return 0 (true) when the certificate lacks DNS:<hostname>.local.
cert_missing_hostname() {
    if openssl x509 -in "$CERT" -noout -text 2>/dev/null |
        grep -q "DNS:${1}.local"; then
        return 1
    fi
    return 0
}

build_san() {
    local hostname expected
    hostname=$(hostname)
    expected=$(expected_hostname || true)
    local san="DNS:localhost,DNS:wlanpi.local,DNS:${hostname}.local"
    if [ -n "$expected" ] && [ "$expected" != "$hostname" ]; then
        san="$san,DNS:${expected}.local"
    fi
    echo "$san,IP:127.0.0.1,IP:198.18.42.1"
}

generate() {
    mkdir -p "$NGINX_SSL_DIR" "$COCKPIT_CERTS_DIR"
    openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
        -keyout "$KEY" -out "$CERT" \
        -subj "/CN=wlanpi.local/O=wlanpi/OU=wlanpi" \
        -addext "subjectAltName=$(build_san)"
    chmod 654 "$CERT"
    chmod 650 "$KEY"
    cp "$KEY" "$COCKPIT_CERTS_DIR/0-self-signed-wlanpi.key"
    cp "$CERT" "$COCKPIT_CERTS_DIR/0-self-signed-wlanpi.cert"
    cp "$KEY" "$NGINX_SSL_DIR/self-signed-grafana.key"
    cp "$CERT" "$NGINX_SSL_DIR/self-signed-grafana.cert"
    chmod 654 "$NGINX_SSL_DIR/self-signed-grafana.cert"
    chmod 650 "$NGINX_SSL_DIR/self-signed-grafana.key"
    if getent group grafana >/dev/null 2>&1; then
        chgrp grafana "$NGINX_SSL_DIR/self-signed-grafana.key" \
            "$NGINX_SSL_DIR/self-signed-grafana.cert"
    fi
    if getent group wlanpi >/dev/null 2>&1; then
        chgrp wlanpi "$KEY" "$CERT"
    fi
}

main() {
    local expected
    expected=$(expected_hostname || true)

    if [ -f "$CERT" ] && [ -f "$KEY" ]; then
        if [ -n "$expected" ] && cert_missing_hostname "$expected"; then
            echo "Existing certificate lacks ${expected}.local; regenerating"
        else
            echo "Self-signed certificates already present and current"
            exit 0
        fi
    fi

    generate
    echo "Self-signed certificates generated"
}

main "$@"