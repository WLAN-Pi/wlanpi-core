# Note from MDK

new packages needed:
- vlan


need to enable 8021q:
echo 8021q >> /etc/modules
create `/etc/modules-load.d/8021q.conf` with contents instead
echo "# Load 802.1q module for VLAN support" > /etc/modules-load.d/8021q.conf
echo 8021q >> /etc/modules-load.d/8021q.conf

alternative, `modprobe 8021q` at runtime


process for vlan management: /etc/network/interfaces.d/vlans
need to create /etc/network/interfaces.d/vlans


Announce config changes via Dbus so C&C can detect them and update!

may need to restart networking, or at least the affected interface:

either 
`sudo ifdown wlan0 && sudo ifup wlan0` or
`sudo ip addr flush interface-name && sudo systemctl restart networking`

## TODO

Proabbly migrate these notes and delete this file 
