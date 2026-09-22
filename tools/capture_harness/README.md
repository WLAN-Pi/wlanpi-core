# Capture WebSocket test harness

A standalone client for the wlanpi-core packet-capture WebSocket
(`/api/v1/streaming/capture`). Use it to exercise the capture protocol,
verify authentication and the owner/subscriber model, and eyeball a live AP
scan without Wireshark. It is a **test/QA tool and a reference client**, not a
production consumer.

## Install

```bash
pip install websockets
```

Python 3.9+. The pcapng / radiotap / 802.11 dissection is built in — no scapy.

## Get a token

The WebSocket authenticates with a wlanpi-core JWT. On the device:

```bash
sudo getjwt harness --no-color
```

Copy the `access_token` value and either pass it with `--token` or export it:

```bash
export WLANPI_CAP_TOKEN='eyJ...'
```

## Connect target

Production uses the TLS-only nginx listener:

```bash
./capture_harness.py list \
    --url wss://localhost:31415/api/v1/streaming/capture \
    --ca-cert /etc/nginx/ssl/self-signed-wlanpi.cert
```

For local development, point `--url` at the app server directly:

```bash
sudo venv/bin/python -m wlanpi_core --debug --reload   # listens on :8000
```

Default `--url` is `ws://localhost:8000/api/v1/streaming/capture`. The
development server is loopback-only; use the production `wss://` URL remotely.

## Modes

### 1. Build a config

```bash
./capture_harness.py config --interface wlanpi0 --channels 1,6,11,36,149 \
    --width 20 --dwell 300 --out lab.json
```

`--channels` are channel numbers (2.4/5 GHz inferred); use `--freqs` for
explicit MHz (needed for 6 GHz, e.g. `--freqs 5955,5975`). Output mirrors the
WebSocket `configure` payload exactly, so it feeds straight into `run`.

### 2. Run a capture (owner)

```bash
export WLANPI_CAP_TOKEN='eyJ...'
./capture_harness.py run --config lab.json --duration 30 --raw-out scan.pcapng
```

Authenticates, configures, starts the capture, prints the **session id**, then
shows a rolling AP scan every few seconds. `--raw-out` also saves the raw
pcapng for opening in Wireshark. Ctrl-C stops cleanly.

### 3. Subscribe (read-only, second instance)

You do **not** need the owner's capture command or config to attach — only a
session id, and you can discover that yourself. Two ways from another terminal
(optionally a different token, to prove cross-principal read access):

Discover by interface (no session id needed — the harness runs `list_sessions`
and picks the capture on that interface; there is only one owner per interface):

```bash
./capture_harness.py run --subscribe-interface wlanpi0 --duration 30
```

Or, if you already have the id (the owner prints a ready-to-paste command as a
convenience):

```bash
./capture_harness.py run --subscribe cap_ab12cd34 --duration 30
```

The subscriber prints a `SUBSCRIBER` banner and the owner's running config
(channels, width, dwell, filter) learned from the `SUBSCRIBED` event — it is
never blind to what it receives — then the identical binary stream. It cannot
control the capture and stops receiving when the owner stops or disconnects.

The owner prints an `OWNER` banner. If the interface you ask to capture is
already owned by another session, the owner run warns you (with the
`--subscribe` command to observe it instead) before `start` fails with
`INTERFACE_IN_USE`.

### 4. List sessions

```bash
./capture_harness.py list
```

Each session is printed with its running config (channels, dwell, filter), so
you can see what an existing capture is doing before deciding to subscribe.

## Example scan output

```
BSSID              CH  SIG SEC       PHY          TXP CC      #  SSID
------------------------------------------------------------------------------
00:11:22:33:44:55   6  -42 WPA2-PSK  g/n/ac/ax     20 GB      1  TestNet

1 AP(s), 0 non-beacon frame(s)
```

Columns: BSSID, channel, last signal (dBm), security (Open/WEP/WPA/WPA2-PSK/
WPA2-Ent/WPA3/WPA2/3), PHY amendments present (g/a + n/ac/ax/be), TX power
(dBm, from radiotap or a TPC report IE), country code, beacon count, SSID.

## Single-radio devices

On a Pi whose capture interface shares one radio (phy) with the managed
`wlan0`, channel hopping can stutter or fail while `wlan0` scans. For
glitch-free hopping either take the managed interface down
(`sudo ip link set wlan0 down` — not over a Wi-Fi SSH session) or use an
external adapter with its own phy. Core retries a transiently-busy channel set
once; a persistent failure appears as a `CHANNEL_SET_FAILED` event carrying the
`iw` reason.

Core sets the requested channel once at capture start, but does not hold it. If
another monitor vif on the same phy is active (e.g. `wlan0mon` driven by the
Kismet daemon, which channel-hops the shared radio continuously), that vif
retunes the radio during the capture, so the stream may carry frames from
whatever channel the phy currently holds rather than the configured one. This
is expected shared-phy behavior, not a core bug.

### Hold a fixed channel when Kismet is running

Kismet's teardown removes the monitor vifs it manages, so stop it, then
recreate the capture vif (`wlanpi0`), before starting the capture:

```bash
sudo systemctl stop kismet
# Recreate the capture vif if Kismet's teardown removed it.
sudo iw phy phy0 interface add wlanpi0 type monitor
sudo ip link set wlanpi0 up
# Cycle the vif if the phy was left wedged by the teardown
# (iw reports "Device or resource busy" on the channel set otherwise).
sudo ip link set wlanpi0 down && sudo ip link set wlanpi0 up
```

Run the capture as normal; the configured channel now holds and the stream
carries frames from it. Restart Kismet when done:

```bash
sudo systemctl start kismet
```

Skipping the stop step means the radio follows Kismet's channel hops instead of
the configured channel.

## Subscriber buffering

How long a subscriber survives before core evicts it with close code 1013, and
how the queue budget and send timeout affect that, is covered in
[`subscriber_buffering/`](subscriber_buffering/README.md). It includes a
deterministic in-process test and a device test that stalls a live subscriber.

## Dissector scope

Deliberately minimal: radiotap first-present-word fields (channel, signal, TX
power) and the IEs SSID, DS channel, country, RSN/WPA, HT/VHT/HE/EHT presence,
and TPC-report TX power. For full analysis, open the `--raw-out` pcapng in
Wireshark.
