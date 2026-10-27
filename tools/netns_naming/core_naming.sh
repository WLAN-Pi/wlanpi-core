#!/bin/bash
# Drives the running wlanpi-core API through namespace moves on two hwsim radios
# and shows what each one does to interface names. Run on a WLAN Pi as a sudo user:
#
#   tools/netns_naming/core_naming.sh            # all scenarios
#   SCENARIOS="S2 S6" tools/netns_naming/core_naming.sh
#
# It activates its own profile (nsexp-a), so whatever profile is active is torn
# down by Core and re-activated at the end. The real radios are not moved.
# The token comes from getjwt and is never printed.
set -u
S=$(cd "$(dirname "$0")" && pwd); API=https://127.0.0.1:31415/api/v1/network/config; NS=nsa
SCENARIOS=${SCENARIOS:-"S1 S2 S3 S4 S5 S6"}
eval "$(sudo getjwt --no-color --export netns-naming-test 2>/dev/null)"; [ -n "${WLANPI_TOKEN:-}" ] || { echo "getjwt gave no token"; exit 1; }
api() { curl -sk -X "$1" -H "Authorization: Bearer $WLANPI_TOKEN" -H 'Content-Type: application/json' ${3:+-d "$3"} -w ' [%{http_code}]' "$API$2" | python3 -I "$S/fmt.py"; }
show() {
  local out="  [$1]"
  for where in root $NS; do
    local pre=(); [ $where = root ] || pre=(ip netns exec $NS)
    local ifs; ifs=$(sudo "${pre[@]}" iw dev 2>/dev/null | awk '/^phy#/{p=$1}/Interface/{n=$2}/ifindex/{i=$2}/type/{if(n!=""){printf "%s:%s(ifx%s,%s) ",p,n,i,$2};n=""}')
    out="$out $where{ $ifs}"
  done; echo "$out"
}
hwphys() { HP1=$(grep -l '^02:00:00:00:00:00' /sys/class/ieee80211/*/macaddress | cut -d/ -f5); HP2=$(grep -l '^02:00:00:00:01:00' /sys/class/ieee80211/*/macaddress | cut -d/ -f5)
  N1=$(ls /sys/class/ieee80211/$HP1/device/net 2>/dev/null | head -1); N2=$(ls /sys/class/ieee80211/$HP2/device/net 2>/dev/null | head -1)
  echo "  hwsim radios: $HP1=${N1:-none} (mac ..00:00)  $HP2=${N2:-none} (mac ..01:00)"; }
normalize() { # profile inactive, namespace gone, each hwsim phy in root with one managed netdev: wlan1 / wlan2
  api POST "/deactivate/nsexp-a?override_active=true" >/dev/null
  for p in $(sudo ip netns exec $NS iw dev 2>/dev/null | awk '/^phy#/{print $1}'); do sudo ip netns exec $NS iw $p set netns 1; done
  sudo ip netns del $NS 2>/dev/null
  for n in wlan1 wlan2 wlan3 $(ls /sys/class/net | grep -E '^wlanpi[0-9]+$'); do
    [ -e /sys/class/net/$n ] && ! [ -e /sys/class/net/$n/phy80211 ] && sudo ip link del $n   # dummies only
  done
  for p in $HP1 $HP2; do for n in $(ls /sys/class/ieee80211/$p/device/net 2>/dev/null); do sudo iw dev $n del; done; done
  sudo iw phy $HP1 interface add wlan1 type managed; sudo iw phy $HP2 interface add wlan2 type managed; hwphys
}
profile() { printf '{"id":"nsexp-a","roots":[],"namespaces":[{"mode":"managed","iface_display_name":"scana","phy":"%s","interface":"%s","security":null,"default_route":false,"namespace":"%s"}]}' "$1" "$2" "$NS"; }
want() { case " $SCENARIOS " in *" $1 "*) return 0;; *) return 1;; esac; }

PREV=$(sudo cat /home/wlanpi/.local/share/wlanpi-core/netcfg/current.txt 2>/dev/null || echo default)
lsmod | grep -q mac80211_hwsim || { sudo modprobe mac80211_hwsim radios=2 || exit 1; sleep 1; }
echo "=== setup (active profile before: $PREV)"; hwphys; normalize
api DELETE "/nsexp-a?force=true" >/dev/null; echo "  create profile nsexp-a: $HP1 / $N1 -> $NS as scana"; api POST "/" "$(profile $HP1 $N1)"

if want S1; then echo "=== S1 plain round trip: Core deletes and recreates the managed netdev, so its name is pinned"
  api POST "/activate/nsexp-a?override_active=true"; show S1-active
  api POST "/deactivate/nsexp-a"; show S1-back; normalize; fi

if want S2; then echo "=== S2 Core's monitor (wlanpi<phyidx>) travels with the phy; its name is taken when it comes back"
  MON=wlanpi${HP1#phy}; sudo iw phy $HP1 interface add $MON type monitor; sudo ip link set $MON up
  api POST "/activate/nsexp-a?override_active=true"; show S2-active
  sudo ip link add $MON type dummy   # stand-in for anything that now owns that name in root
  api POST "/deactivate/nsexp-a"; show S2-back
  echo "  -> profile says interface=$N1; $HP1 now carries: $(ls /sys/class/ieee80211/$HP1/device/net | tr '\n' ' ')"
  api POST "/activate/nsexp-a?override_active=true"; show S2-reactivate; normalize; fi

if want S3; then echo "=== S3 a phy in the namespace that the profile does not list: bulk revert moves it as it is"
  api POST "/activate/nsexp-a?override_active=true"
  sudo iw phy $HP2 set netns name $NS; sudo ip link add $N2 type dummy; show S3-active
  api POST "/deactivate/nsexp-a"; show S3-back
  echo "  -> $HP2 now carries: $(ls /sys/class/ieee80211/$HP2/device/net | tr '\n' ' ')"; normalize; fi

if want S4; then echo "=== S4 probe-order swap: the name wlan1 now belongs to the other radio; which radio does Core move?"
  sudo ip link set $N1 name swaptmp; sudo ip link set $N2 name $N1; sudo ip link set swaptmp name $N2; hwphys
  api POST "/activate/nsexp-a?override_active=true"; show S4-active
  echo "  -> radio in $NS has mac $(sudo ip netns exec $NS cat /sys/class/net/scana/address 2>/dev/null) (profile was written for ..00:00)"
  api POST "/deactivate/nsexp-a"; normalize; fi

if want S5; then echo "=== S5 replug: phy index moves on, the name is reused; profile still says $HP1"
  sudo rmmod mac80211_hwsim; sudo modprobe mac80211_hwsim radios=2; sleep 1; hwphys
  api POST "/activate/nsexp-a?override_active=true"; show S5-active
  api POST "/deactivate/nsexp-a"; show S5-back; normalize; fi

if want S6; then echo "=== S6 another radio takes wlan1 while the first is away (what a USB plug-in does: lowest free wlan%d)"
  api POST "/activate/nsexp-a?override_active=true"
  sudo ip link set $N2 name $N1; show S6-active
  api POST "/deactivate/nsexp-a"; show S6-back
  echo "  -> $HP1 now carries: $(ls /sys/class/ieee80211/$HP1/device/net | tr '\n' ' ')"
  api POST "/activate/nsexp-a?override_active=true"; show S6-reactivate; normalize; fi

echo "=== cleanup"; api POST "/deactivate/nsexp-a?override_active=true" >/dev/null; api DELETE "/nsexp-a?force=true"
sudo ip netns del $NS 2>/dev/null; sudo rmmod mac80211_hwsim
[ "$PREV" != default ] && api POST "/activate/$PREV?override_active=true"
show end; echo "  namespaces left: $(ip netns list | tr '\n' ' ')"
echo "=== Core log (errors and naming warnings during this run)"
sudo journalctl -u wlanpi-core --since "-5min" --no-pager | grep -iE 'did not arrive|Config says|exists in several|Keeping namespace|Could not|ERROR -' | grep -v 'wpa_cli\|Status check\|not found' | sed 's/^.*wlanpi-core\[[0-9]*\]: [0-9-]* [0-9:,]* - //' | tail -20
