# WLAN USB/PCI driver endpoints — UI integration guide

**Endpoints:**
- `GET /api/v1/network/wlan/usb-drivers`
- `GET /api/v1/network/wlan/pci-drivers`

**Auth:** Bearer JWT (or localhost HMAC)

**Capabilities:** `network.interfaces.wlan.usb_drivers`, `wifi.radio.usb_drivers`, `network.interfaces.wlan.pci_drivers`

---

## What these endpoints do

Both endpoints start by listing **all** wireless interfaces (`iw dev`). Debug logs such as `Found 2 wireless interfaces` refer to that step only.

They then **filter by hardware bus** and return only matching adapters:

| Endpoint | Includes | Excludes |
|----------|----------|----------|
| **usb-drivers** | USB dongles (e.g. Atheros `ath9k_htc`) | On-board PCI, SDIO, platform Wi-Fi |
| **pci-drivers** | PCI and platform/SDIO interfaces (e.g. `wlan0`, `wlanpi0` on Intel `iwlwifi`) | USB dongles |

On a WLAN Pi Pro / R4 with built-in Intel Wi-Fi, **`usb-drivers` legitimately returns an empty `adapters` array**. That is not an error. Use **`pci-drivers`** for on-board radios.

---

## Response shapes

### USB drivers

```json
{
  "adapters": [
    {
      "interface": "wlan1",
      "driver": "ath9k_htc",
      "bus": "usb"
    }
  ],
  "interfaces_scanned": 2
}
```

### PCI drivers

```json
{
  "adapters": [
    {
      "interface": "wlan0",
      "driver": "iwlwifi",
      "bus": "pci"
    },
    {
      "interface": "wlanpi0",
      "driver": "iwlwifi",
      "bus": "pci"
    }
  ],
  "pci_devices": [
    {
      "pci_id": "0000:01:00.0",
      "description": "Network controller: Intel Corporation Wi-Fi 7 ..."
    }
  ],
  "interfaces_scanned": 2
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `adapters` | array | Interfaces that passed bus filter, with driver name |
| `adapters[].interface` | string | Linux netdev (`wlan0`, `wlanpi0`, …) |
| `adapters[].driver` | string \| null | From `ethtool -i`; null if ethtool unavailable |
| `adapters[].bus` | string | `usb`, `pci`, or `platform` |
| `interfaces_scanned` | number | How many `iw dev` interfaces were checked |
| `pci_devices` | array | (pci-drivers only) Raw `lspci` wireless lines |

---

## UI parsing rules

1. **Always expect HTTP 200** on success, even when `adapters` is empty.
2. **Do not treat empty `adapters` as failure** — check `interfaces_scanned`:
   - `interfaces_scanned > 0` and `adapters.length === 0` on **usb-drivers** → show “No USB Wi-Fi adapters” and offer pci-drivers data if relevant.
   - `interfaces_scanned === 0` → no wireless interfaces at all (unusual).
3. **Same PHY, multiple interfaces:** `wlan0` and `wlanpi0` often share one chip; pci-drivers may list both with the same `driver`. Display as separate rows or collapse by driver — both are valid.
4. **`pci_devices` vs `adapters`:** `pci_devices` can be non-empty while `adapters` was empty on older core builds; after bus-detection fix they should align on PCI hardware. Prefer `adapters` for per-interface driver display.
5. **`driver` null:** Show interface name and bus; omit driver or show “unknown”.

### Suggested empty-state copy

| Endpoint | `interfaces_scanned` | `adapters` | Suggested UI |
|----------|---------------------|------------|--------------|
| usb-drivers | 2 | `[]` | “No USB Wi-Fi adapters detected (2 on-board interfaces scanned)” |
| usb-drivers | 0 | `[]` | “No wireless interfaces found” |
| pci-drivers | 2 | `[…]` | List drivers per interface |

---

## Capability binding

| Capability | Endpoint | When to use |
|------------|----------|-------------|
| `network.interfaces.wlan.usb_drivers` | `GET /network/wlan/usb-drivers` | USB dongle / external adapter menu |
| `network.interfaces.wlan.pci_drivers` | `GET /network/wlan/pci-drivers` | Built-in / M.2 / SDIO Wi-Fi menu |
| `wifi.radio.usb_drivers` | same as usb-drivers | Touch menu alias |

For a **generic “Wi-Fi drivers” screen** on unknown hardware, call **both** endpoints and merge `adapters`, or call pci-drivers first on WLAN Pi images without USB Wi-Fi.

---

## Example (TypeScript)

```typescript
type WlanAdapter = {
  interface: string;
  driver: string | null;
  bus: "usb" | "pci" | "platform";
};

type UsbDriversResponse = {
  adapters: WlanAdapter[];
  interfaces_scanned: number;
};

async function loadWlanDrivers(client: ApiClient) {
  const [usb, pci] = await Promise.all([
    client.get<UsbDriversResponse>("/api/v1/network/wlan/usb-drivers"),
    client.get("/api/v1/network/wlan/pci-drivers"),
  ]);

  const rows = [...usb.adapters, ...pci.adapters];
  if (rows.length === 0 && usb.interfaces_scanned > 0) {
    return {
      rows: [],
      hint: "Radios present but none are USB-attached. Check PCI drivers.",
    };
  }
  return { rows, hint: null };
}
```

---

## Debugging

| Symptom | Likely cause |
|---------|----------------|
| Log shows “Found 2 wireless interfaces” but USB UI is blank | Normal on PCI-only hardware — use pci-drivers |
| Both endpoints empty, `interfaces_scanned: 0` | `iw dev` returned nothing |
| `driver` null | `ethtool -i` failed or needs privileges |
| Duplicate rows same driver | Multiple VIFs on one PHY (expected) |
