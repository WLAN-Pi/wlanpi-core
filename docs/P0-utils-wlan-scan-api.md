# GET /api/v1/utils/wlan/scan — UI integration guide

**Endpoint:** `GET /api/v1/utils/wlan/scan`  
**Auth:** Bearer JWT (remote) or localhost HMAC (`X-Request-Signature`) for on-device services  
**Status:** Live (P0)  
**Supersedes:** `GET /api/v1/network/wlan/scan` (legacy DBus path — do not use for new UI work)

**Related:** [P0 core worker API](./P0-core-worker-api.md) §2.4, [gap matrix](./p0-api-gap-matrix.csv), [OpenAPI `/docs`](../wlanpi_core/asgi.py)

---

## 1. What this endpoint does

Returns a **single snapshot** of visible WiFi networks from one adapter, with namespace-aware adapter selection. Core hides network-namespace complexity from end users.

- **One HTTP request → one scan** (`wpa_cli scan` + parsed results).
- **Not** a continuous or streaming scan. For live RF survey, use `/streaming/capture` (see §8).

---

## 2. Request

```
GET /api/v1/utils/wlan/scan
GET /api/v1/utils/wlan/scan?hidden=false
GET /api/v1/utils/wlan/scan?iface=wlanpi1&namespace=scan_ns
GET /api/v1/utils/wlan/scan?detail=full
```

| Query param | Required | Default | Description |
|-------------|----------|---------|-------------|
| `iface` | No | — | Interface name (e.g. `wlanpi0`, `wlan0`). Omit for auto-selection. |
| `namespace` | No | root | Namespace name, or `root` / omit for default namespace. |
| `hidden` | No | `true` | Include networks with empty SSID in results. |
| `detail` | No | `short` | `short` — list fields plus RF extensions; `full` — also includes per-BSS `raw` iw dump (forces `iw scan`). |

**Headers**

| Header | When |
|--------|------|
| `Authorization: Bearer <token>` | Remote clients (mobile, WebUI) |
| `X-Request-Signature: …` | wlanpi-ui on localhost |

Obtain JWT via `POST /api/v1/auth/token` with `{ "device_id": "…" }`.

---

## 3. Response shapes

All JSON keys are **camelCase** in wire format.

### 3.1 Successful scan (`200`)

```json
{
  "detail": "short",
  "selectedAdapter": {
    "iface": "wlan0",
    "namespace": "root",
    "label": "wlan0 (managed, root)",
    "mode": "managed"
  },
  "networks": [
    {
      "ssid": "MyNetwork",
      "bssid": "aa:bb:cc:dd:ee:01",
      "signal": -52,
      "freq": 2412,
      "key_mgmt": "wpa-psk",
      "minrate": 1000000,
      "flags": "[WPA2-PSK-CCMP][ESS]",
      "primaryChannel": 36,
      "channelWidth": 80,
      "secondaryChannelOffset": "above",
      "bssLoad": { "stations": 4, "utilization": 32 },
      "amendments": ["n", "ac"]
    }
  ],
  "scannedAt": "2026-06-14T12:00:00+00:00",
  "needsSelection": false,
  "candidates": []
}
```

Extended fields (`flags`, `primaryChannel`, `channelWidth`, `secondaryChannelOffset`, `bssLoad`, `amendments`) are populated when the scan backend provides them — typically when core uses `iw dev <iface> scan`. With `wpa_cli scan_results` only, you still get `flags` and `primaryChannel` (derived from frequency); width, offset, load, and amendments may be empty.

| Field | Type | Use |
|-------|------|-----|
| `detail` | string | Echo of request: `short` or `full`. |
| `selectedAdapter` | object \| null | Adapter that was scanned. Always set when `needsSelection` is false and scan ran. |
| `selectedAdapter.iface` | string | Interface name for display and retry params. |
| `selectedAdapter.namespace` | string | `"root"` or namespace name — pass back as `namespace` query param. |
| `selectedAdapter.label` | string | Human-readable label for picker UI. |
| `selectedAdapter.mode` | string \| null | `monitor` or `managed` when known. |
| `networks` | array | BSS list, sorted by signal (strongest first). |
| `networks[].ssid` | string | May be empty for hidden networks when `hidden=true`. |
| `networks[].bssid` | string | Lowercase MAC with colons. |
| `networks[].signal` | int | dBm (typically negative). |
| `networks[].freq` | int | Centre frequency in MHz. |
| `networks[].key_mgmt` | string \| null | `wpa-psk`, `open`, `wep`, or `unknown`. |
| `networks[].minrate` | int | Bitrate hint (default `1000000`). |
| `networks[].flags` | string \| null | Raw security/capability flags (`wpa_cli`) or iw capability line. |
| `networks[].primaryChannel` | int \| null | 802.11 channel number (from iw or derived from `freq`). |
| `networks[].channelWidth` | int \| null | Channel width in MHz when known (20, 40, 80, 160). |
| `networks[].secondaryChannelOffset` | string \| null | HT secondary channel: `none`, `above`, or `below` control channel. |
| `networks[].bssLoad` | object \| null | `stations` count and `utilization` (0–255) from BSS Load IE. |
| `networks[].amendments` | string[] | PHY amendments detected (`n`, `ac`, `ax`, `k`, `v`, `r`, …). |
| `networks[].raw` | string \| null | Full iw BSS block text; only when `detail=full`. |
| `scannedAt` | string \| null | ISO 8601 UTC timestamp when scan completed. |
| `needsSelection` | bool | `false` when scan ran. |
| `candidates` | array | Empty when scan ran. |

### 3.2 Adapter picker required (`200`, no scan)

When **two or more monitor adapters** exist and `iface` is omitted, core returns candidates **without scanning**:

```json
{
  "selectedAdapter": null,
  "networks": [],
  "scannedAt": null,
  "needsSelection": true,
  "candidates": [
    {
      "iface": "wlanpi0",
      "namespace": "root",
      "label": "wlanpi0 (monitor, root)",
      "mode": "monitor"
    },
    {
      "iface": "wlanpi1",
      "namespace": "scan_ns",
      "label": "wlanpi1 (monitor, scan_ns)",
      "mode": "monitor"
    }
  ]
}
```

**UI flow:** show picker → user selects → retry:

```
GET /api/v1/utils/wlan/scan?iface=wlanpi1&namespace=scan_ns
```

### 3.3 No suitable adapter (`422`)

```json
{
  "error": "NO_SCAN_ADAPTER",
  "candidates": []
}
```

Shown when no monitor adapter is available and no managed adapter exists in root. Display a clear error; do not retry in a tight loop.

### 3.4 Server error (`503`)

Plain-text body: `Unable to complete WLAN scan`. Scan failed (e.g. `wpa_cli` error, supplicant not running). Offer retry after delay.

---

## 4. Adapter selection (when `iface` omitted)

Core uses the same adapter layout as `GET /api/v1/network/config/status` (`iw dev` per namespace).

| Condition | HTTP | Behaviour |
|-----------|------|-----------|
| 1 monitor adapter | 200 | Auto-select monitor **role**; active scan may run on managed sibling (e.g. `wlan0` when `wlanpi0` is monitor) |
| 2+ monitor adapters | 200 | `needsSelection: true`; **no scan** |
| 0 monitor, ≥1 managed in root | 200 | Fallback to first managed in root; scan runs |
| 0 suitable adapters | 422 | `NO_SCAN_ADAPTER` |
| `iface` (+ optional `namespace`) set | 200 or 422 | Use named adapter; 422 if not found |

**Device mode:** Scan works in any device mode (classic, hotspot, etc.) as long as adapters exist.

---

## 5. Capability bindings

From [gap matrix](./p0-api-gap-matrix.csv):

| Legacy / UI capability | Endpoint | Notes |
|------------------------|----------|-------|
| `wifi.scan.quick` | `GET /utils/wlan/scan` | Default hidden SSIDs |
| `wifi.scan.full` | `GET /utils/wlan/scan` | Same endpoint |
| `app.scanner.scan` | `GET /utils/wlan/scan` | Bind here |
| `app.scanner.scan_nohidden` | `GET /utils/wlan/scan?hidden=false` | Exclude empty SSID |

**Suggested job metadata (wlanpi-ui):**

| Field | Value |
|-------|-------|
| `freshnessSec` | `30` |
| `coreEndpoint` | `/api/v1/utils/wlan/scan` |
| `pollOnMount` | `true` |

---

## 6. Recommended UI integration patterns

### 6.1 One-shot (settings, connect wizard)

```
1. GET /utils/wlan/scan
2. If needsSelection → show candidates → GET with iface + namespace
3. Render networks[] (SSID, signal bar, security icon from key_mgmt)
```

### 6.2 Periodic updates (scanner screen, TUI)

Implement in **wlanpi-ui job layer**, not core:

```
1. Start job with freshnessSec: 30
2. Loop: GET /utils/wlan/scan → merge/diff networks[] → push on job WebSocket
3. Stop job on screen exit
```

Core remains stateless. Throttle client-side (≥15–30s) to avoid hammering `wpa_cli scan`.

### 6.3 MCP / AI / automation

- Call the same REST endpoint.
- Parse `networks[]` and `selectedAdapter`.
- Handle `needsSelection` by returning candidate list to the model/user for disambiguation.
- No WebSocket required in core for MCP.

### 6.4 Third-party HTTP clients

- Stable schema: OpenAPI at `/docs` tag **device utils**.
- Auth: JWT as documented in [P0 core worker API](./P0-core-worker-api.md) §2.1.
- Idempotent read: safe to retry on 503.

---

## 7. Example client flows

### TypeScript

```typescript
type ScanAdapter = {
  iface: string;
  namespace: string;
  label: string;
  mode?: string | null;
};

type WlanNetwork = {
  ssid: string;
  bssid: string;
  signal: number;
  freq: number;
  key_mgmt?: string | null;
  minrate: number;
};

type ScanResponse = {
  selectedAdapter: ScanAdapter | null;
  networks: WlanNetwork[];
  scannedAt: string | null;
  needsSelection: boolean;
  candidates: ScanAdapter[];
};

async function fetchScan(
  baseUrl: string,
  authHeaders: HeadersInit,
  params?: { iface?: string; namespace?: string; hidden?: boolean }
): Promise<ScanResponse> {
  const qs = new URLSearchParams();
  if (params?.iface) qs.set("iface", params.iface);
  if (params?.namespace) qs.set("namespace", params.namespace);
  if (params?.hidden === false) qs.set("hidden", "false");

  const res = await fetch(`${baseUrl}/api/v1/utils/wlan/scan?${qs}`, {
    headers: authHeaders,
  });

  if (res.status === 422) {
    const err = await res.json();
    throw new Error(err.error ?? "NO_SCAN_ADAPTER");
  }
  if (!res.ok) throw new Error(`Scan failed: ${res.status}`);

  return res.json();
}

// Picker flow
const first = await fetchScan(baseUrl, headers);
if (first.needsSelection) {
  const pick = first.candidates[0]; // or user choice
  const second = await fetchScan(baseUrl, headers, {
    iface: pick.iface,
    namespace: pick.namespace,
  });
  console.log(second.networks);
} else {
  console.log(first.networks);
}
```

### Dart / Flutter

```dart
@JsonSerializable()
class ScanResponse {
  @JsonKey(name: 'selectedAdapter')
  final ScanAdapter? selectedAdapter;
  final List<WlanNetwork> networks;
  @JsonKey(name: 'scannedAt')
  final String? scannedAt;
  @JsonKey(name: 'needsSelection')
  final bool needsSelection;
  final List<ScanAdapter> candidates;
}
```

Wire JSON uses **camelCase** keys (`selectedAdapter`, `scannedAt`, `needsSelection`). Do not apply `fieldRename: FieldRename.snake` to these models.

---

## 8. What this endpoint is not

| Need | Use instead |
|------|-------------|
| Continuous live BSS stream | `/streaming/capture` WebSocket (passive pcap; future beacon parser) |
| Connection / provisioning status | `GET /network/config/status`, namespace activate APIs |
| Connected network details | `GET /network/wlan/getConnected` (legacy; migrating off DBus) |
| Legacy FPMS scan shape (`nets[]`) | Migrate to `networks[]` on this endpoint |

Do **not** implement continuous scan by polling this endpoint faster than ~15s or by adding a core WebSocket that loops `wpa_cli scan`.

---

## 9. Hardware notes (WLAN Pi + iwlwifi)

Classic WLAN Pi layout: **`wlanpi0` monitor** + **`wlan0` managed** on the same PHY.

| Check | Typical result |
|-------|----------------|
| `wpa_cli` on `wlanpi0` | Fails — no supplicant on monitor VIF |
| `iw dev wlanpi0 scan` | Often **-95 Operation not supported** |
| `ip link set wlan0 up` + `iw dev wlan0 scan` | **Works** (active scan on managed VIF) |

Core behaviour:

1. User/monitor **selection** may still prefer the monitor adapter when picking among monitors.
2. **Execution** delegates active scan to a **managed sibling in the same namespace** when present.
3. `selectedAdapter` in the response reflects the **interface that actually scanned** (usually `wlan0`, not `wlanpi0`).
4. Scan path: `wpa_cli` when supplicant is running, otherwise **`iw dev <iface> scan`** (interface brought up first).

No network namespace is involved when `ip netns list` is empty — failures on stock classic images are driver/mode, not netns.

---

## 10. Timing and UX expectations

- A single scan typically takes **2–5 seconds** (trigger + poll for results).
- Show a loading state; disable repeat-tap while in flight.
- `signal` is dBm: map to bars with clamping (e.g. -90 … -30).
- Empty `networks[]` after 200 is valid (no APs heard); distinguish from `needsSelection`.

---

## 11. Testing reference

Matrix scenarios in `tests/scenarios/p0_api_test_matrix.csv`:

| Scenario | Expected |
|----------|----------|
| `scan_auto_single_monitor` | 200, networks populated |
| `scan_needs_selection_multi_monitor` | 200, `needsSelection`, empty networks |
| `scan_explicit_iface_namespace` | 200, matching `selectedAdapter` |
| `scan_fallback_managed_root` | 200, managed adapter selected |
| `scan_no_adapter` | 422, `NO_SCAN_ADAPTER` |

---

## 12. Changelog

| Date | Change |
|------|--------|
| 2026-06-14 | iwlwifi: delegate monitor selection to managed sibling; `iw scan` fallback without wpa_supplicant |
| 2026-06-14 | Initial Live endpoint; namespace-aware selection; `wpa/scan.py` shared primitives |
