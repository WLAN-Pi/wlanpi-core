# TLS front-ends for the core API and wlanpi-mcp

wlanpi-core can terminate TLS in nginx for two LAN-exposed HTTP services, using
the self-signed device certificate its postinst already generates for the WebUI,
Cockpit and Grafana. Both front-ends are **feature-flagged and off by default**:
installing a build that contains them changes nothing until a flag is flipped.

| Front-end | Flag | Listener | Proxies to | Cleartext sibling |
|---|---|---|---|---|
| Core API | `WLANPI_CORE_TLS_API` | `https://<device>:31416` | `unix:/run/wlanpi_core.sock` | `http://<device>:31415` (unchanged) |
| wlanpi-mcp | `WLANPI_CORE_TLS_MCP` | `https://<device>:8767` | `http://127.0.0.1:8766` | `http://<device>:8766` (see below) |

nginx does TLS and proxying only. Authentication is unchanged and stays in
wlanpi-core (`verify_auth_wrapper`) and wlanpi-mcp; the `X-Real-IP` core sees
is always the true client address.

## Enabling

Flags live in `/etc/wlanpi-core/tls.conf` (a conffile). The helper edits the
file, links or unlinks the nginx sites, opens or closes the matching UFW
application profiles (`wlanpi-core-tls`, `wlanpi-mcp-tls`), validates with
`nginx -t`, and reloads nginx:

```bash
sudo wlanpi-core-tls enable api
```

```bash
sudo wlanpi-core-tls enable mcp
```

```bash
sudo wlanpi-core-tls status
```

`disable api|mcp` reverses a flag; `apply` reconciles nginx/UFW with whatever
the file says (the package postinst runs `apply`, so flags survive upgrades).

### When enabling the MCP front-end

The MCP daemon binds `0.0.0.0:8766` by default, so cleartext MCP stays reachable
from the LAN even with the TLS front-end up. For a secure deployment:

1. Bind MCP to loopback: `WLANPI_MCP_HOST=127.0.0.1` in `/etc/wlanpi-mcp/config.env`,
   then restart `wlanpi-mcp`.
2. Do not open 8766 in the firewall. wlanpi-core's UFW profiles never open it.
3. Point MCP clients at `https://<device>:8767/...` (the wlanpi-mcp docs for the
   transport in use apply unchanged apart from scheme and port).

## Trusting the certificate

The certificate is self-signed (RSA-4096, 10 years) with SANs `localhost`,
`wlanpi.local`, `127.0.0.1` and the OTG address — **not** the device's DHCP
address or hostname. Connect by `wlanpi.local` (mDNS) where possible.

Fetch the certificate once from the device and trust it explicitly rather than
disabling verification:

```bash
scp wlanpi@wlanpi.local:/etc/nginx/ssl/self-signed-wlanpi.cert ./wlanpi.cert
```

Then, per client:

- curl: `curl --cacert ./wlanpi.cert https://wlanpi.local:31416/api/v1/...`
- Python requests/httpx: `verify="./wlanpi.cert"`
- Node-based MCP bridges (e.g. `mcp-remote`): `NODE_EXTRA_CA_CERTS=./wlanpi.cert`
- Browsers / OS keychains: import as a trusted certificate for this device only

In a classroom, distribute each device's certificate with its credentials.
Accepting any certificate on first connect (TOFU) is an acceptable fallback on
a trusted network but leaves an active attacker able to present their own.

## Testing against a development instance

Development runs core directly under uvicorn, bypassing gunicorn and nginx:

```bash
sudo venv/bin/python -m wlanpi_core --debug --reload
```

That listens on `0.0.0.0:8000`, so the production TLS sites (which proxy to
the gunicorn unix socket) never see it. A third, development-only front-end
proxies TLS to the dev server instead, using the same cert and the same proxy
block as production — so TLS clients, `X-Forwarded-Proto`, and the
credential-dispatch behaviour can be exercised against live code:

```bash
sudo wlanpi-core-tls enable dev
```

```bash
curl --cacert ./wlanpi.cert https://wlanpi.local:8443/api/v1/system/device/info -H "Authorization: Bearer $TOKEN"
```

| Front-end | Flag | Listener | Proxies to |
|---|---|---|---|
| Dev core | `WLANPI_CORE_TLS_DEV` | `https://<device>:8443` | `http://127.0.0.1:8000` |

If the dev server runs with a different `--port`, change the `proxy_pass`
target in `wlanpi_core_tls_dev.conf` to match. Leave this flag off on deployed
devices; it is not part of any production configuration.

Note the dev server itself still answers plain HTTP on `:8000` from the LAN —
the TLS front-end adds an encrypted path, it does not remove the cleartext one.

## Transition plan for `:31415`

The plain HTTP API listener is intentionally untouched in this phase so
deployed clients (notably the WLAN Pi app, which speaks plain Bearer to
`:31415`) keep working. Once clients present TLS + the device cert, the
follow-up is to restrict `:31415` to loopback (internal HMAC clients still need
it) or remove it, and to consider moving the API TLS listener onto `:31415`
itself. That is a deliberate, separate change with its own flag.

## Adding a listener

Site files live in `install/etc/wlanpi-core/nginx/` and are installed to
`/etc/wlanpi-core/nginx/sites-enabled/` without being linked. The API TLS
site's `location /` block must stay identical to `wlanpi_core.conf`'s;
`tests/test_nginx_tls_config.py` enforces that, validates the files with
`nginx -t` when nginx is available, and exercises the helper's link/unlink
logic against a temporary tree.
