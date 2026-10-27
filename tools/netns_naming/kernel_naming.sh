#!/bin/bash
# What the kernel does to wireless netdev names on a namespace move.
#
# Uses two mac80211_hwsim radios, so it never touches a real radio and runs
# on any WLAN Pi. Needs root. Leaves nothing behind (unloads hwsim at the end).
#
#   sudo tools/netns_naming/kernel_naming.sh
#
# Each step prints the root and test namespace inventory as phy#N:name.
set -u
NS=nsnametest
show() { echo "  [$1] root{ $(iw dev | awk '/^phy#/{p=$1}/Interface/{printf "%s:%s ",p,$2}')} $NS{ $(ip netns exec $NS iw dev 2>/dev/null | awk '/^phy#/{p=$1}/Interface/{printf "%s:%s ",p,$2}')}"; }
hw() { # HP1/HP2: hwsim phys by permanent MAC; N1/N2: their netdevs
  HP1=$(grep -l '^02:00:00:00:00:00' /sys/class/ieee80211/*/macaddress | cut -d/ -f5)
  HP2=$(grep -l '^02:00:00:00:01:00' /sys/class/ieee80211/*/macaddress | cut -d/ -f5)
  N1=$(ls /sys/class/ieee80211/$HP1/device/net | head -1); N2=$(ls /sys/class/ieee80211/$HP2/device/net | head -1)
}
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
lsmod | grep -q mac80211_hwsim && { echo "mac80211_hwsim already loaded; unload it first"; exit 1; }
modprobe mac80211_hwsim radios=2 || exit 1; sleep 1; hw
ip netns del $NS 2>/dev/null; ip netns add $NS
echo "hwsim radios: $HP1=$N1  $HP2=$N2"; show start

echo "== 1. ip link set netns on a wireless netdev is refused; only the whole phy moves (iw phy set netns)"
ip link set $N1 netns $NS 2>&1 | sed 's/^/   /'

echo "== 2. the name is taken in the target: kernel renames to the lowest free wlan%d there"
ip netns exec $NS ip link add wlan0 type dummy; ip netns exec $NS ip link add $N1 type dummy
iw phy $HP1 set netns name $NS; show 2
echo "   (ifindex kept when free in the target: $(ip netns exec $NS sh -c 'cat /sys/class/net/*/ifindex' | tr '\n' ' '))"

echo "== 3. a rename inside the namespace works while the netdev is down"
got=$(ip netns exec $NS iw dev | awk '/Interface/{print $2}'); ip netns exec $NS ip link set "$got" name radioA; show 3

echo "== 4. sibling netdevs travel too and get wlan%d when their name is taken: a wlanpiN monitor becomes wlanN"
ip netns exec $NS iw phy $HP1 interface add wlanpi$HP1 type monitor
ip link add $N1 type dummy; ip link add wlanpi$HP1 type dummy
ip netns exec $NS iw phy $HP1 set netns 1; show 4

echo "== 5. 'iw interface add <taken name>' fails with -23 (ENFILE), not EEXIST: that is what a name clash looks like"
iw phy $HP1 interface add $N1 type managed 2>&1 | sed 's/^/   /'

echo "== 6. not a counter: free the names and the next arrival takes the lowest free one again"
ip link del $N1; ip link del wlanpi$HP1; ip netns exec $NS ip link del wlan0 2>/dev/null; ip netns exec $NS ip link del $N1 2>/dev/null
iw phy $HP2 set netns name $NS; show 6a; ip netns exec $NS iw phy $HP2 set netns 1; show 6b

echo "== 7. replug: phy index only ever goes up; netdev names are reused"
rmmod mac80211_hwsim; modprobe mac80211_hwsim radios=2; sleep 1; hw; show 7
echo "   phys now: $(ls /sys/class/ieee80211 | tr '\n' ' ') (a phy can be renamed: iw phy $HP2 set name <new>)"

echo "== 8. udev: a .link matched on PermanentMACAddress renames at probe AND on return to root (udev does not run inside a netns)"
mkdir -p /run/systemd/network
printf '[Match]\nPermanentMACAddress=02:00:00:00:00:00\n[Link]\nName=pinnedA\n' > /run/systemd/network/10-netns-naming-test.link
udevadm control --reload
iw phy $HP1 set netns name $NS; ip netns exec $NS iw phy $HP1 set netns 1; udevadm settle; show 8a
rmmod mac80211_hwsim; modprobe mac80211_hwsim radios=2; udevadm settle; sleep 1; show 8b
rm -f /run/systemd/network/10-netns-naming-test.link; udevadm control --reload

ip netns del $NS; rmmod mac80211_hwsim; echo "done; hwsim unloaded"
