#!/bin/bash
# initial install script for wlanpi-core
#
# WARNING: this modifies other packages configuration files

set -e 

echo "Starting wlanpi_core install fixup script ..."

# nginx configuration file location
NGINX_CONF=/etc/nginx/nginx.conf

# if conf exists, create backup and then overwrite it
if [ -f "$NGINX_CONF" ]; then
    TSTAMP=`date '+%s'`
    NEW_CONF="$NGINX_CONF.$TSTAMP"
    echo "Existing nginx.conf detected; creating backup to $NEW_CONF ..."
    mv $NGINX_CONF $NEW_CON

    # overwrite without prompting
    \cp /etc/wlanpi-core/nginx/nginx.conf $NGINX_CONF

    # if we changed a nginx config file, test config, and restart nginx.
    echo "Testing nginx config ..."
    nginx -t
    echo "Invoking restart of nginx.service ..."
    deb-systemd-invoke restart nginx.service
fi

# Deny wlanpi-core from SSH Access if it is not already denied
SSHD_CONFIG=/etc/ssh/sshd_config
if ! grep -q "DenyUsers wlanpi-core" $SSHD_CONFIG; then
    echo "Denying wlanpi-core from SSH Access ..."
    cat << EOF >> $SSHD_CONFIG

# Deny SSH access to wlanpi-core user
DenyUsers wlanpi-core
EOF

sshd -t
fi

# create log directory and set permissions for apiuser
DIR="/var/log/wlanpi_core/"

# if DIR does not exist, create it
if [ ! -d "$DIR" ]; then
    echo "$DIR does not exist, creating it ..."
    mkdir -p ${DIR}
fi

# set $DIR permissions for apiuser
if id -u ${APIUSER} > /dev/null 2>&1; then    
    echo "Fix up permissions on $DIR for $APIUSER ..."
    chown ${APIUSER}:${GROUPID} ${DIR}
fi

echo "Adding wlanpi-core to sudoers ..."
visudo -c -q -f /etc/wlanpi-core/sudoers.d/wlanpi-core && \
chmod 600 /etc/wlanpi-core/sudoers.d/wlanpi-core && \
cp /etc/wlanpi-core/sudoers.d/wlanpi-core /etc/sudoers.d/wlanpi-core

echo "Invoking restart of wlanpi-core.service ..."
deb-systemd-invoke restart wlanpi-core.service

echo "Finished wlanpi_core install fixup script ..."
exit 0
