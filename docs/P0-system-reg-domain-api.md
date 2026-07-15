# GET /api/v1/system/reg-domain — app integration guide

**Endpoint:** `GET /api/v1/system/reg-domain`  
**List:** `GET /api/v1/system/reg-domain/list`  
**Set:** `POST /api/v1/system/reg-domain/set` with `{ "country": "GB" }`  
**Auth:** Bearer JWT

## List supported countries

`GET /api/v1/system/reg-domain/list` returns the country records present in the
appliance's active Linux `wireless-regdb` database:

```json
{
  "countries": [
    { "code": "US", "name": "United States" },
    { "code": "GB", "name": "United Kingdom" }
  ]
}
```

| Field | Use |
|-------|-----|
| `countries[].code` | Value for set + comparison with current `country` |
| `countries[].name` | Display label in pickers |

The exact list follows the installed `wireless-regdb` package and can change with
regulatory database updates. SET rejects codes absent from that database with **400**.

## Current domain response

```json
{
  "country": "GB",
  "raw": "GB",
  "source": "wlanpi-reg-domain"
}
```

| Field | Type | Use |
|-------|------|-----|
| `country` | string | **Always use this.** ISO 3166-1 alpha-2 (two letters) |
| `raw` | string \| null | Diagnostic output only — do not parse |
| `source` | string | `wlanpi-reg-domain`, `iw`, or `crda` — debugging only |

## Why GET failed before (fixed in core)

Core was calling `wlanpi-reg-domain show`, but the on-device script only accepts **`get`**:

```bash
wlanpi-reg-domain get   # prints: GB
wlanpi-reg-domain show  # prints: Error: Invalid option
```

That produced `"country": "unknown"` with `"raw": "Error: Invalid option"`.

SET worked because it already used `wlanpi-reg-domain set XX`.

## Flutter / Dart

```dart
Future<String?> fetchRegDomain(ApiClient client) async {
  final response = await client.get('/api/v1/system/reg-domain');
  if (response.statusCode != 200) return null;

  final body = jsonDecode(response.body) as Map<String, dynamic>;
  final country = body['country'] as String?;
  if (country == null || country.length != 2 || country == 'unknown') {
    return null;
  }
  return country.toUpperCase();
}
```

```dart
@JsonKey(name: 'country')
final String countryCode;
// Ignore raw/source in UI models unless debugging
```

## Set regulatory domain

```dart
await client.post(
  '/api/v1/system/reg-domain/set',
  body: jsonEncode({'country': 'GB'}),
);
```

Returns the same `RegDomainInfo` shape as GET after a successful set.

## Debugging

With wlanpi-core at DEBUG log level:

```
GET /system/reg-domain request
get_reg_domain: wlanpi-reg-domain get stdout='GB' ...
get_reg_domain: parsed country='GB' source='wlanpi-reg-domain'
GET /system/reg-domain response: {'country': 'GB', ...}
```

If `country` cannot be parsed, core returns **503** (not 200 with `"unknown"`).

## Note on log noise

Shell-pipeline commands (RAM, disk, uptime on `/system/info`) no longer emit injection warnings. Auth and reg-domain debug lines only appear when log level is DEBUG.
