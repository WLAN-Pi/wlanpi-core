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
sudo getjwt harness -p 8000 --no-color
```

Copy the `access_token` value and either pass it with `--token` or export it:

```bash
export WLANPI_CAP_TOKEN='eyJ...'
```

## Connect target

Point `--url` at the core server's HTTP port directly, e.g. the dev server:

```bash
sudo venv/bin/python -m wlanpi_core --debug --reload   # listens on :8000
```

Default `--url` is `ws://localhost:8000/api/v1/streaming/capture`. For another
host use `ws://wlanpi.local:8000/api/v1/streaming/capture`.

> nginx TLS front-ends do not forward the WebSocket upgrade yet, so `wss://`
> through nginx (`:31416` / `:8443`) will not work until that lands. Connect to
> the app/dev HTTP port for now.

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

The owner prints a ready-to-paste subscribe command. From another terminal
(optionally a different token, to prove cross-principal read access):

```bash
./capture_harness.py run --subscribe cap_ab12cd34 --duration 30
```

The subscriber receives the identical binary stream but cannot control the
capture. It stops receiving when the owner stops or disconnects.

### 4. List sessions

```bash
./capture_harness.py list
```

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

## Dissector scope

Deliberately minimal: radiotap first-present-word fields (channel, signal, TX
power) and the IEs SSID, DS channel, country, RSN/WPA, HT/VHT/HE/EHT presence,
and TPC-report TX power. For full analysis, open the `--raw-out` pcapng in
Wireshark.
