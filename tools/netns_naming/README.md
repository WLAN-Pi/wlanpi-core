# Namespace naming harness

Two scripts that show what happens to wireless interface names when a radio
moves between network namespaces. Both use `mac80211_hwsim` virtual radios,
so they run on any WLAN Pi without touching the real radios, and both unload
hwsim when they finish.

`kernel_naming.sh` (run as root) needs no Core. It demonstrates the kernel
rules: only a whole phy moves (`iw phy set netns`), every netdev on it
travels, a name that is taken in the target becomes the lowest free `wlan%d`
there, `iw interface add` on a taken name fails with `-23`, the phy index
only ever goes up, and a `.link` file matched on `PermanentMACAddress` renames
a netdev at probe and on return to root.

`core_naming.sh` (run as a sudo user, Core running) drives the real API
through scenarios S1 to S6 with a throwaway profile `nsexp-a`. Pick a subset
with `SCENARIOS="S2 S6"`. It tears down the active profile for the duration
and re-activates it at the end.

| Scenario | What it shows |
|---|---|
| S1 | A plain round trip: Core deletes and recreates the managed netdev, so its name is pinned. |
| S2 | Core's `wlanpiN` monitor travels unpinned; if its name is taken on return it becomes `wlanN`, Core's recreate of `wlan1` then fails with `-23`, the API returns 500 and the radio is left under the display name. |
| S3 | A phy in the namespace that the profile does not list is returned by the bulk revert with no pinning and silently renamed on collision. |
| S4 | Names swapped between two radios (probe order): the profile follows the name, so the wrong radio is moved. Only a warning is logged. |
| S5 | A replug moves the phy index on; the stale `phy` in the profile is tolerated because the name still matches. |
| S6 | Another radio takes `wlan1` while the first is away: deactivate reports success but takes down the wrong radio, the first comes home as `scana`, and the next activation moves the wrong radio. |

Read the inventory lines as `phy#N:name(ifindex,type)` for root and the test
namespace `nsa`.

The table describes Core before radios were pinned by MAC (#237). With that
fix, S2 and S6 deactivate cleanly (a renamed monitor is removed, a taken root
name falls back to the next free `wlanN`), S4 moves the pinned radio whatever
it is called, and reactivation finds the radio by MAC. S3 is unchanged: a phy
the profile does not list is handed back as it is.
