#!/bin/bash
# initial install script
# warning: this modifies other packages configuration files

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

# create api user and set permissions
APIUSER="wlanpi_api"
GROUPID="wlanpi_api"

if id ${APIUSER} &>/dev/null; then
    echo "User $APIUSER already exists, skipping ..."
else
    echo "User $APIUSER does not exist, creating ..."
    choose() { echo ${1:RANDOM%${#1}:1} $RANDOM; }
    pass="$({ choose '!@#$%^\&'
        choose '0123456789'
        choose 'abcdefghijklmnopqrstuvwxyz'
        choose 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        for i in $( seq 1 $(( 4 + RANDOM % 8 )) )
            do
                choose '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
            done
        } | sort -R | awk '{printf "%s",$1}')"
    echo "User $APIUSER created ..."
    if [ $(getent group $APIUSER) ]; then
        useradd ${APIUSER} -g ${APIUSER} -s /bin/false
    else
        useradd ${APIUSER} -s /bin/false
    fi

    # if user is not in group, add them.
    if ! id -nGz "$APIUSER" | grep -qzxF "$GROUPID"; then
        echo User \`$APIUSER\' does not belong to group \`$GROUPID\'
        usermod -g ${GROUPID} ${APIUSER}
        echo "User $APIUSER added to group $GROUPID"    
    fi
    echo $APIUSER:$pass | chpasswd
    echo "Assigned random password to $APIUSER"
fi

# Deny wlanpi_api from SSH Access if it is not already denied
SSHD_CONFIG=/etc/ssh/sshd_config
if ! grep -q "DenyUsers wlanpi_api" $SSHD_CONFIG; then
    echo "Denying wlanpi_api from SSH Access ..."
    cat << EOF >> $SSHD_CONFIG

# Deny SSH access to wlanpi_api user
DenyUsers wlanpi_api
EOF

sshd -t
fi

# create log directory and set permissions for apiuser
DIR="/var/log/wlanpi-core/"

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

echo "Adding wlanpi_api to sudoers ..."
visudo -c -q -f /etc/wlanpi-core/sudoers.d/wlanpi_api && \
chmod 600 /etc/wlanpi-core/sudoers.d/wlanpi_api && \
cp /etc/wlanpi-core/sudoers.d/wlanpi_api /etc/sudoers.d/wlanpi_api

echo "Invoking restart of wlanpi-core.service ..."
deb-systemd-invoke restart wlanpi-core.service

echo "Finished wlanpi_core install fixup script ..."
exit 0
