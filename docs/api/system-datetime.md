# GET /api/v1/system/datetime — app integration guide

**Endpoint:** `GET /api/v1/system/datetime`  
**Auth:** Bearer JWT (or localhost HMAC for on-device services)

## Response shape

```json
{
  "datetime": "2026-06-07T21:32:12+01:00",
  "timezone": "Europe/London",
  "display": "Sun  7 Jun 21:32:12 BST 2026",
  "source": "date"
}
```

| Field | Type | Use |
|-------|------|-----|
| `datetime` | string | **Always parse this.** ISO 8601 / RFC 3339 with numeric UTC offset |
| `timezone` | string | IANA name when available (`Europe/London`). May be a legacy code on some images |
| `display` | string \| null | Human-readable label — show as-is; **do not parse** |
| `source` | string | `date`, `timedatectl`, or `fallback` — for debugging only |

## Why apps failed to parse (fixed in core)

Earlier builds used `timedatectl show -p LocalTime --value`, which is **empty** on many WLAN Pi images (systemd exposes `TimeUSec` instead). That produced `"datetime": ""`, which breaks all parsers.

Core now uses `date -Iseconds`, which always returns a parseable ISO string like `2026-06-07T21:32:12+01:00`.

## Flutter / Dart

```dart
import 'dart:convert';

Future<DateTime?> fetchDeviceDateTime(ApiClient client) async {
  final response = await client.get('/api/v1/system/datetime');
  if (response.statusCode != 200) return null;

  final body = jsonDecode(response.body) as Map<String, dynamic>;
  final iso = body['datetime'] as String?;
  if (iso == null || iso.isEmpty) return null;

  // ISO 8601 with offset — preferred
  return DateTime.parse(iso);
}

// Display without parsing:
String displayLabel(Map<String, dynamic> body) {
  return body['display'] as String? ??
      body['datetime'] as String? ??
      'Unknown';
}
```

**Do not** use `DateTime.parse` on `display`.

**JSON key:** the field is literally `"datetime"` (lowercase). Ensure generated models use:

```dart
@JsonKey(name: 'datetime')
final String dateTimeIso;
```

## JavaScript / TypeScript

```typescript
const res = await fetch('/api/v1/system/datetime', { headers: authHeaders });
const body = await res.json();
const dt = new Date(body.datetime); // ISO 8601
const label = body.display ?? body.datetime;
```

## Capability binding (`sys.tz.show` / `system.date`)

| Capability | Endpoint | Display |
|------------|----------|---------|
| `sys.tz.show` | `GET /system/datetime` | `display` or formatted `datetime` |
| `sys.tz.get` | `GET /system/timezone` | `timezone` field only |

## Debugging

With wlanpi-core started using `--debug`:

```
GET /system/datetime request
get_datetime: date -Iseconds='2026-06-07T21:32:12+01:00' timezone='Europe/London' display='...'
GET /system/datetime response: {'datetime': '...', ...}
```

If `datetime` is empty, core returns **503** (not 200 with an empty string).

## Related endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/system/timezone` | Current TZ name only |
| GET | `/system/timezone/list` | All zones |
| POST | `/system/timezone/set` | `{ "timezone": "Europe/London" }` |
