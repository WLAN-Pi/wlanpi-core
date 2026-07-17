# GET /api/v1/utils/reachability and /speedtest — UI integration guide

**Endpoints:**
- `GET /api/v1/utils/reachability`
- `GET /api/v1/utils/speedtest`

**Auth:** Bearer JWT (remote) or localhost HMAC (`X-Request-Signature`) for on-device services  
**Status:** Live (P0)

**Related:** [P0 core worker API](./P0-core-worker-api.md) §4 Stream C, [gap matrix](./p0-api-gap-matrix.csv)

---

## 1. Reachability

Runs a **single parallel batch** of network health checks:

- Ping Google (`google.com`)
- Browse Google (HTTP check)
- Ping default gateway
- ARPing default gateway (L2)
- DNS resolution against up to three configured resolvers
- Optional **custom targets** you supply (ICMP ping with structured stats)

One HTTP request → one test run. Not streaming.

### 1.1 Request

```
GET /api/v1/utils/reachability
GET /api/v1/utils/reachability?targets=8.8.8.8,1.1.1.1
GET /api/v1/utils/reachability?targets=8.8.8.8&targets=cloudflare.com
```

| Query param | Required | Default | Description |
|-------------|----------|---------|-------------|
| `targets` | No | — | Hostnames or IPs to ping. Repeat the parameter or use comma-separated values. Max **10** unique targets. |

### 1.2 Successful response (`200`)

Built-in checks use the **legacy display keys** (unchanged for fpms2 / existing UI bindings):

```json
{
  "Ping Google": "5.17ms",
  "Browse Google": "OK",
  "Ping Gateway": "1.12ms",
  "DNS Server 1 Resolution": "OK",
  "Arping Gateway": "2ms",
  "custom": [
    {
      "target": "8.8.8.8",
      "success": true,
      "rttMsMin": 5.17,
      "rttMsAvg": 5.17,
      "rttMsMax": 5.17,
      "packetLossPercent": 0.0,
      "display": "5.17ms"
    },
    {
      "target": "192.0.2.1",
      "success": false,
      "rttMsMin": null,
      "rttMsAvg": null,
      "rttMsMax": null,
      "packetLossPercent": 100.0,
      "display": "FAIL"
    }
  ]
}
```

| Field | Type | Use |
|-------|------|-----|
| `Ping Google` | string | RTT like `5.17ms` or `FAIL` |
| `Browse Google` | string | `OK` or `FAIL` |
| `Ping Gateway` | string | RTT or `FAIL` |
| `DNS Server N Resolution` | string \| omitted | `OK` or `FAIL` when resolver N exists |
| `Arping Gateway` | string | RTT like `2ms` or `FAIL` |
| `custom` | array | Empty when `targets` omitted; structured ping stats per custom host |
| `custom[].target` | string | Echo of requested host/IP |
| `custom[].success` | bool | `true` when at least one reply received |
| `custom[].rttMsMin` | number \| null | Min RTT in ms (`jc ping`) |
| `custom[].rttMsAvg` | number \| null | Average RTT in ms |
| `custom[].rttMsMax` | number \| null | Max RTT in ms |
| `custom[].packetLossPercent` | number \| null | Packet loss percent |
| `custom[].display` | string | Same style as built-in pings: `5.17ms` or `FAIL` |

DNS fields are omitted (not `null`) when fewer than N resolvers are configured — same as before.

### 1.3 Errors

| HTTP | When |
|------|------|
| **400** | Invalid `targets` value, or more than 10 targets |
| **503** | No default gateway / network config could not be read |
| **500** | Unexpected server error |

```json
{ "error": "invalid ping target: bad;host" }
```

### 1.4 Capability binding

| Capability | Endpoint |
|------------|----------|
| `utils.reachability` | `GET /utils/reachability` |

Custom cloud reachability (`cloud.arista`, etc.) remains a separate future worker (`GET /utils/cloud-test/{vendor}`).

---

## 2. Speedtest

Runs **LibreSpeed CLI** (`librespeed-cli --json --simple`). Typically **30–90 seconds**.

### 2.1 Request

```
GET /api/v1/utils/speedtest
```

No query parameters.

### 2.2 Successful response (`200`)

```json
{
  "ipAddress": "217.155.247.50",
  "downloadSpeed": "495.79 Mbps",
  "uploadSpeed": "690.97 Mbps",
  "pingMs": 5.0,
  "jitterMs": 0.0,
  "server": "London, England (Clouvider)",
  "testedAt": "2026-06-14T17:38:48+00:00"
}
```

| Field | Type | Use |
|-------|------|-----|
| `ipAddress` | string | Public IP seen by the speedtest server |
| `downloadSpeed` | string | Human-readable download rate |
| `uploadSpeed` | string | Human-readable upload rate |
| `pingMs` | number \| null | ICMP/ping RTT to selected server |
| `jitterMs` | number \| null | Jitter to selected server |
| `server` | string \| null | Selected LibreSpeed server name |
| `testedAt` | string \| null | ISO 8601 UTC timestamp from LibreSpeed |

### 2.3 Errors

| HTTP | When |
|------|------|
| **503** | Binary failed, parse error, or timeout (120s server-side cap) |
| **500** | Unexpected server error |

```json
{ "error": "speedtest timed out" }
```

### 2.4 UI job wrapper

| Setting | Value |
|---------|-------|
| Capability | `utils.speedtest` |
| Core endpoint | `GET /api/v1/utils/speedtest` |
| `freshnessSec` | **10** (UI platform dedup — avoid duplicate runs) |
| Pattern | UI→Core job + optional job WebSocket progress |

Core is stateless: wlanpi-ui should cache/dedupe within the freshness window.

---

## 3. Example (localhost HMAC)

```bash
# Reachability with custom pings
lhapitest -e /utils/reachability -q "targets=8.8.8.8,1.1.1.1" -p 8000

# Speedtest (long-running)
lhapitest -e /utils/speedtest -p 8000
```

---

## 4. Changelog

| Date | Change |
|------|--------|
| 2026-06-14 | Added `targets` query param and `custom[]` ping stats on reachability |
| 2026-06-14 | Added `GET /utils/speedtest` (LibreSpeed CLI wrapper) |
