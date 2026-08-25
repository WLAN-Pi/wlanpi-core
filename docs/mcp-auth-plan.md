# MCP Authentication & Transport Plan (wlanpi-core / wlanpi-mcp)

**Status:** Draft for discussion — candidate companion to [#139](https://github.com/WLAN-Pi/wlanpi-core/issues/139)
**Scope:** How a user (student), an MCP client harness, wlanpi-mcp, and wlanpi-core authenticate to each other — for the Prague release and beyond.
**Deployment model assumed:** one WLAN Pi per student. The student *owns* their device. Adversaries are other people on the shared classroom LAN, not co-users of the same box. Other on-box or companion apps may mint their own tokens (per-`device_id` tokens are already supported by core).

---

## 1. Current implementation analysis and fit for MCP

### 1.1 What exists today

| Layer | Today | Where |
|---|---|---|
| Auth dispatch | By **source IP**: loopback → HMAC required, anything else → Bearer JWT. Not by presented credential. | `wlanpi_core/core/auth.py` (`verify_auth_wrapper`) |
| MCP workaround | nginx rewrites `X-Wlanpi-Client: mcp` → `X-Real-IP: 192.0.2.1` so localhost MCP traffic takes the JWT branch. Merged as a bridge; #139 tracks its removal. | `install/etc/wlanpi-core/nginx/wlanpi_core.conf` |
| Tokens | HS256 (symmetric key in SQLite), claims `sub/iss/did/exp/iat/kid/jti`. **No `aud`**. Issued via HMAC bootstrap (`getjwt <device-id>`), 7-day default TTL, revocable, DB-backed. | `wlanpi_core/core/token.py` |
| Transport | Core API `:31415` and MCP `:8766` are **cleartext HTTP**. TLS (self-signed, 10-year cert) exists only for WebUI/Cockpit/Grafana. | nginx configs, `debian/postinst` |
| MCP server | Legacy HTTP+SSE on `:8766`, **forwards the user's core JWT unchanged** (passthrough), binds session to `sha256(token)`. Runs as `User=wlanpi`. | wlanpi-mcp repo |

### 1.2 Defects found during this review (all verified in code / on-device)

These matter because several prior design assumptions rest on them:

1. **The HMAC shared secret is readable by MCP today.** `shared_secret.bin` is created `root:wlanpi` mode `0640` (`wlanpi_core/core/security.py`), and `wlanpi-mcp.service` runs as `User=wlanpi Group=wlanpi`. The stated justification for the #135 nginx sentinel — "MCP cannot read the HMAC secret" — is factually wrong on current images. Everything running as user `wlanpi` is in the HMAC trust class, whether we like it or not. Any "dedicated MCP service credential" adds no isolation until these permissions are tightened.
2. **Revocation does not reliably take effect.** `TokenManager.verify_token` returns success from the in-process token cache **without checking the revoked flag**, and `revoke_token` never evicts the cache entry. A revoked token keeps working until the cache happens to clear (hourly purge, only when expired rows were deleted) or the service restarts.
3. **JWT expiry is not enforced.** `time_validation_enabled = False`: the `exp` claim is never validated and `is_expired` is hard-coded `False`. Expiry only bites when the hourly purge task deletes the DB row (~1h granularity). Any "short TTL" recommendation is fiction until this is enabled.
4. **OTG stub is an auth-bypass landmine.** If `is_otg_request()` ever returns `True`, `verify_auth_wrapper` falls through and returns with **no authentication performed**. Dead code today; must not stay this shape.

### 1.3 Fit against the MCP specification (2026-07-28)

The current live MCP spec revision is stateless at the protocol layer (SEP-2567): no `initialize` handshake, no `Mcp-Session-Id`, every JSON-RPC message is an independent `POST /mcp` carrying its own `Authorization` header; `Origin` validation is mandatory; **token passthrough is forbidden** for a spec-conformant resource server.

| Spec expectation | wlanpi-mcp today | Gap severity |
|---|---|---|
| Streamable HTTP `POST /mcp`, stateless | HTTP+SSE `:8766/sse` + session | Transport migration needed (client compat driver, not a security hole) |
| Bearer validated by MCP on every request, audience-bound | Bearer checked at SSE open, forwarded to core, no `aud` | Architectural — see §3 |
| No token passthrough | Full passthrough | Spec deviation — acceptable short-term on a single-box appliance (see §2.1), wrong long-term |
| Origin validation / DNS-rebinding defence | None; binds `0.0.0.0:8766` | Needed when we expose HTTP transport |
| TLS | None on either hop | **The actual live vulnerability** — tokens sniffable on the classroom LAN |

**Important nuance:** the spec's passthrough ban is written for multi-party cloud topologies (confused-deputy, audience mixing). On a single-operator appliance where core is both the token issuer and the only upstream, passthrough's *practical* marginal risk is near zero — the real Prague risks are cleartext transport, non-working revocation, and unenforced expiry. That is what drives the Prague/beyond split below.

### 1.4 Multiple token-holding apps — and the WLAN Pi app today

Core's model already supports "other apps mint their own tokens": each app calls `getjwt <its-device-id>` (or the pairing flow) and gets an independent, independently-revocable token with its own `did` claim. Nothing new is required for Prague except (a) making revocation/expiry actually work (§1.2), and (b) deciding cross-app rights on shared resources like streams (Appendix A).

**The WLAN Pi app is the only deployed third-party API consumer today.** Its bootstrap is: SSH to the device → run `sudo getjwt <app-device-id>` → use the returned 7-day JWT as a Bearer against `:31415`. Two consequences for this plan:

- It is the **compatibility baseline**: any auth change must keep (i) `getjwt`'s invocation and JSON output stable, and (ii) plain Bearer access to the core API working for tokens without new claims. §5 analyses this.
- Its SSH-based pairing is functional but clunky (requires SSH credentials to mint an API token — a stronger credential bootstrapping a weaker one). Marked as an **evolution item (B6)**: replace SSH+`getjwt` with a first-class pairing flow (one-time code shown on the front panel/WebUI, or OAuth device-code), with `getjwt` retained for headless/scripted use.

---

## 2. MCP for Prague — good security with minimal new scope

### 2.1 Security stance

Keep JWT passthrough for Prague, **documented as an accepted, temporary deviation** from the MCP spec, and spend the budget on the controls that stop real attacks:

- **Threats addressed:** LAN sniffing/MITM of tokens (other students), token theft from disk, tokens that outlive the class, inability to kill a compromised token, blast-radius of MCP tooling.
- **Threats consciously deferred:** confused-deputy via passthrough (single-box, single-owner — negligible), OAuth-grade client onboarding, per-scope authorization.

### 2.2 The "session" model (user-facing)

The user's request — session-based interaction, with next-day continuity under a renewed token — maps cleanly onto the stateless spec **without** re-introducing protocol sessions:

- **Identity = the JWT** (short-lived: default TTL ~24h for interactive use). "Log in for today's lab" = obtain/renew the token once (initial auth is acceptable per requirements).
- **Continuity = ownership bound to `did`, not to the token string.** Captures, jobs, and handles are owned by the `did` claim. A renewed token with the same `did` picks up yesterday's artifacts exactly. Nothing is lost at token rollover.
- **No `Mcp-Session-Id`, no server-side login session.** The "session" the student experiences is (valid token for today) + (their persistent, `did`-owned state on the device).

This gives the desired UX and is forward-compatible with the stateless transport in §3.

### 2.3 Prague work items (summary — details in §4.1)

1. **#139 as specified:** dispatch on presented credentials (Bearer present → JWT validation regardless of source IP; HMAC only when a signature header is present), remove the nginx sentinel map, MCP drops `X-Wlanpi-Client`. Kill the OTG fall-through while in the file.
2. **Make expiry and revocation real:** enable time validation; evict revoked tokens from the cache; add a `ttl`/`expires_delta` option to token issuance; default interactive tokens to ~24h.
3. **TLS on both hops via nginx** with the existing self-signed cert: HTTPS vhost for `:31415` and for MCP (prefer proxying MCP under `443` at `/mcp`, or a TLS `:8766`). UFW updated accordingly. Distribute/pin the device cert to the class (or accept TOFU on `wlanpi.local`) — stated honestly: self-signed TLS defeats passive sniffing; an *active* MITM requires cert pinning or trust distribution, which a classroom can do once.
4. **Token hygiene:** the harness reads `WLANPI_MCP_TOKEN` from its environment; no literal tokens in any client config; committed examples secret-free. Be precise about **where** the token lives and what "env" buys us:
   - **Location: the student's client machine** (where the MCP client/harness runs) — not the Pi. The Pi never needs a stored user token: it holds the HMAC secret and *mints* tokens. (Exception: stdio-mode MCP running on the Pi itself reads an env file such as `~/.config/wlanpi/mcp.env`, 0600 — but any process running as that user on the Pi can already run `getjwt`, so this stores nothing that user couldn't obtain anyway.)
   - **Env is a mitigation, not a vault.** It is strictly better than a token pasted into `mcp.json` (which is typically world-readable, synced to cloud backups, and prone to being committed), but a token exported in a shell profile is still plaintext at rest, and any process running as the same user can read it (including via `/proc/<pid>/environ`). The gold path on the client is **OS keychain → injected into the client's env at launch**; a plain env file chmod 600 is the acceptable floor.
   - **Why the floor is acceptable for Prague:** the blast radius of a leaked token is one student's own Pi, for ≤24h (P2), revocable (P2), read-mostly (P5 allowlist). We are not protecting a long-lived admin credential.
5. **MCP tool allowlist for class profiles:** default classroom config exposes read/scan/capture tools; service restart / reboot / network reconfig behind an "instructor" config flag.
6. **Capture over WS with auth (#141) + `did`-owned handles**, so MCP capture tooling ships at Prague. Rights model in Appendix A.

### 2.4 Harness (MCP client) — free / cost-effective options

TBD per requirements; candidates to evaluate, cheapest first:

| Option | Cost | Notes |
|---|---|---|
| **MCP Inspector** (official) | Free | Great for teaching the protocol itself; not an LLM harness. |
| **Claude Desktop / Claude Code (free tier) + stdio or remote MCP** | Free tier | Simplest polished UX; verify current free-tier remote-connector limits before committing. |
| **Open-source clients** (Cline, LibreChat, other OSS MCP hosts) | Free software; pay per LLM API token | Bring-your-own model key; a single classroom API key with per-student budgets is the cost-effective pattern. |
| **Tiny custom harness** on the MCP Python/TS SDK | Free + API tokens | Most control (can bake in the Pi's cert + env token handling); more to maintain. |

Whatever is chosen, the Prague contract it must meet is small: send `Authorization: Bearer $WLANPI_MCP_TOKEN` from env, trust the distributed device cert, speak SSE now / Streamable HTTP later.

---

## 3. MCP beyond Prague — the full architecture

Target: wlanpi-mcp as a spec-conformant **OAuth 2.1 resource server** on MCP Streamable HTTP.

1. **Transport:** stateless `POST /mcp` (Python SDK `stateless_http=True`), `Origin` allowlist, behind nginx TLS on 443. Legacy SSE listener retired (or kept briefly as a compat shim returning 405 on GET per spec).
2. **Audience-bound tokens:** core issues `aud=mcp` tokens for MCP clients (and `aud=core` for direct API clients). MCP rejects non-MCP-audience tokens.
3. **MCP validates tokens itself — via core introspection, not JWKS.** Because tokens are HS256 + DB-backed revocation, MCP cannot self-validate offline and a JWKS is impossible for symmetric keys. Core adds an HMAC-protected `POST /api/v1/auth/introspect`; MCP calls it per request with a short-TTL cache. (Asymmetric signing + JWKS is a later, optional migration — only worth it if off-box validators appear.)
4. **No passthrough + service identity + identity assertion.** MCP calls core with its own service credential and asserts the validated user identity (`did`) inside the HMAC-signed request body so core keeps per-user attribution, audit, rate limits, and handle-ownership checks. *Without the assertion piece, dropping passthrough silently destroys per-user attribution — this is the step most designs miss.*
5. **Tighten the secret trust boundary** so the service identity means something: `shared_secret.bin` → root-only (0600); MCP gets its own provisioned credential; anything still running as `wlanpi` no longer implicitly holds core's master HMAC secret.
6. **Pairing UX:** OAuth 2.1 device-code or WebUI consent replaces copy-from-terminal `getjwt`; client stores tokens in its own secret store. RFC 9728 protected-resource metadata + 401 `WWW-Authenticate` for auto-discovery.
7. **Scopes/roles:** tokens carry scopes (`read`, `capture`, `admin`) so "other apps with their own tokens" can be least-privileged, and the classroom/instructor split becomes a token property instead of an MCP config flag.

---

## 4. Implementation plan

### 4.1 Prague elements

| # | Item | Repo | Size | Notes |
|---|---|---|---|---|
| P1 | Credential-based auth dispatch; remove nginx sentinel; remove OTG fall-through | wlanpi-core | S | This **is** #139; tests already enumerated on the issue |
| P2 | Revocation cache eviction fix; boot-bound monotonic lifetime (`bid`/`upt`); `ttl` on issuance; `TOKEN_LIFETIME_MODE` (`wall_clock_grace` default, 7-day `ACCESS_TOKEN_EXPIRE_DAYS`; `boot_bound` optional) | wlanpi-core | S | Makes P4/P5 meaningful; small diffs in `token.py` / `config.py` |
| P3 | Feature-flagged nginx TLS front-ends (off by default): `:31416` core API, `:8767` MCP, `:8443` dev uvicorn; plain `:31415` unchanged; UFW via `wlanpi-core-tls`; existing postinst self-signed cert | wlanpi-core (+pi-gen) | S–M | **Landed** on `feature/tls-frontends` (#162): capture WS also proxied over `wss://:31416`; UFW profiles; `nginx -t` tested; runbook `docs/TLS.md` |
| P3.1 | `:31415` transition (post-Prague): `WLANPI_CORE_HTTP_API` (LAN cleartext on/off → loopback-only HTTP for HMAC/`getjwt` when off); `WLANPI_CORE_TLS_API_PORT` (`31416` default, or `31415` only when LAN HTTP is off); coordinate WLAN Pi app cert trust before removing cleartext | wlanpi-core (+WLAN Pi app) | S | Deliberate migration after P3; not part of the initial TLS PR |
| P4 | `getjwt --export` / `--write-env` (0600) + stderr warning; docs stop showing paste-into-config | wlanpi-core | S | |
| P5 | MCP: drop `X-Wlanpi-Client`; HTTPS endpoint docs; classroom tool-allowlist profile; token from env only | wlanpi-mcp | S | Depends on P1, P3 |
| P6 | Capture WS auth (#141) + `did`-owned sessions + read-only subscribers (Appendix A policy A) | wlanpi-core | M | **Landed** on `feature/capture-auth` (#165): first-message auth (4401), owned sessions with config/namespace descriptor, subscribe-by-interface, namespace-aware capture, `ws://` nginx proxy, reference harness + `docs/capture-ws-mcp-handover.md` |
| P7 | MCP capture tools using explicit handles (start/status/frames/stop) | wlanpi-mcp | M | Depends on P6 |
| P8 | Harness selection + one-page student setup guide (token env, cert trust) | docs | S | TBD harness decision gates the guide only |
| P9 | WebUI front-door auth: session login + CSRF on mutating routes (Appendix B) | wlanpi-webui | M | Closes the live anonymous confused-deputy hole; Prague candidate — see B.3 |
| P10 | Core route-auth guard rail: CI test asserting every route carries an auth dependency or is on an explicit public allowlist | wlanpi-core | S | Core is clean today (only the #141 WS lacks auth); this keeps it that way |

Dependency chain: P1 → P5; P2 independent; P3 → P5/P8; P3.1 after P3 and app cert-trust coordination; P6 → P7. P1–P4 are individually small and can land as separate PRs immediately.

### 4.2 Beyond-Prague elements

| # | Item | Repo | Notes |
|---|---|---|---|
| B1 | Streamable HTTP `POST /mcp` stateless transport + Origin allowlist; retire SSE | wlanpi-mcp | Client compat driver; do when chosen harness supports it |
| B2 | `aud` claim issuance + audience enforcement | wlanpi-core, wlanpi-mcp | Prereq for B3 |
| B3 | `POST /auth/introspect` (HMAC-protected) + MCP per-request validation w/ short cache | wlanpi-core, wlanpi-mcp | Ends passthrough on the validation side |
| B4 | MCP service credential + signed `did` assertion to core; core authorizes on asserted identity | wlanpi-core, wlanpi-mcp | Ends passthrough on the upstream side; preserves attribution |
| B5 | Secret permissions tightening (0600 root-only) + provisioned per-service credentials | wlanpi-core | Do together with B4 |
| B6 | Pairing flow to replace SSH+`getjwt` bootstrap: one-time code on front panel/WebUI, or OAuth 2.1 device-code; RFC 9728 metadata | wlanpi-core, wlanpi-mcp, WLAN Pi app | Replaces SSH-run `getjwt` for humans and for the WLAN Pi app; `getjwt` kept for headless/scripted use |
| B7 | Scoped tokens (read/capture/admin) | wlanpi-core | Folds classroom profile into token policy |
| B8 | (Optional) asymmetric signing + JWKS | wlanpi-core | Only if off-box token validation becomes a need |
| B9 | WebUI leaves the privileged class: browser holds its own scoped core token; WebUI serves static assets only | wlanpi-webui, wlanpi-core | Appendix B option 2; follows P9, B5, B7 |

---

### 4.3 CI tests

Every security property above must be pinned by a test that fails when the property regresses. Grouped by repo and type; Prague items are test-gated with their PRs (a P-item is not "done" until its tests are in CI).

#### wlanpi-core — pytest (unit/API, run on every PR)

| Backs | Test cases |
|---|---|
| P1 (#139) | Bearer from a **loopback** source validates as JWT (no HMAC demanded); HMAC signature from loopback validates; loopback request with **neither** credential → 401; non-loopback with valid Bearer → 200; non-loopback without Bearer → 401; request carrying **both** → defined precedence (Bearer wins) asserted; `X-Wlanpi-Client` header has **no effect** on dispatch |
| P1 (OTG) | `verify_auth_wrapper` has no code path returning `None`/unauthenticated — property test: for every combination of (source, headers) with invalid or missing credentials, the result is 401/403, never success |
| P2 (revocation) | Issue token → verify (populates cache) → revoke → **immediate** re-verify fails (this is the cache-eviction regression test; it fails on today's code); revoke unknown/already-revoked token → stable status responses |
| P2 (expiry / lifetime) | Token issued with `ttl=1s` → verify after expiry fails via `exp` (not via purge); `iat`/`exp` claims present and consistent; default mode is `wall_clock_grace` with 7-day ceiling; `boot_bound` mode ties validity to monotonic uptime (`bid`/`upt`) and is pinned by explicit tests |
| P2 (rotation) | After `rotate_key`, old-key tokens fail immediately including from cache |
| P6 (WS auth) | Connect without auth frame within window → closed 4401; valid first-message auth → subscribed; revoked/expired token → refused; **owner** can stop, non-owner valid token cannot (403); non-owner valid token **can** subscribe (policy A) — flips if C is chosen; renewed token (same `did`, new string) retains ownership of an existing handle; token in query string is rejected (forces the safe handshake) |
| P10 (guard rail) | Iterate `app.routes`; assert each route's dependencies include `verify_auth_wrapper`/`verify_hmac` **or** the route is in an explicit `PUBLIC_ROUTES` allowlist checked into the repo; WS routes included; test fails on any new unlisted route |
| B2–B4 (when they land) | Token minted with `aud`; core accepts legacy no-`aud` token (lenient mode pinned by test so the compat promise in §5.1 can't silently break); introspection endpoint: valid/revoked/expired/malformed; identity assertion: core authorizes handle ops on asserted `did`, tampered assertion (bad HMAC) rejected |

#### wlanpi-core — static/lint checks (fast job, every PR)

| Backs | Check |
|---|---|
| P1 | nginx configs under `install/etc/wlanpi-core/nginx/` contain **no auth-related header rewriting**: grep-fails on `map $http_x_wlanpi_client`, hardcoded `X-Real-IP` sentinels, or any `proxy_set_header` derived from a client-supplied identity header (this is #139's acceptance criterion, executable) |
| P3 | `nginx -t` against the shipped configs in CI (container with nginx-light); TLS vhosts reference the postinst cert paths, listen on `:31416`/`:8767`/`:8443` (never replace plain `:31415` in the same PR); flags default off; UFW rules file parses; helper link/unlink logic exercised |
| P4 | Repo-wide secret scan: no `eyJ`-prefixed literals in docs/examples/tests fixtures (allowlist for deliberately-invalid sample tokens); `getjwt --write-env` output file asserted mode `0600` in its unit test; no code path writes under `.cursor/` or `claude_desktop_config.json` |
| P2/B5 | `SecurityManager` sets secret file mode/owner as specified (0640 root:wlanpi now; flips to 0600 root-only with B5 — the test encodes the *current* policy so tightening is a deliberate test change) |

#### wlanpi-mcp — pytest + lint

| Backs | Test cases |
|---|---|
| P5 | Outbound requests to core carry **no** `X-Wlanpi-Client` header; classroom profile config exposes only the allowlisted tools (service restart/reboot absent); token read from `WLANPI_MCP_TOKEN` env only — token passed as argv/config literal is refused |
| P5 (lint) | Committed example configs (`mcp.json`, `claude_desktop_config.json`, `.mcp.json`) are secret-free: grep-fail on `eyJ` |
| P7 | Capture tools: handle from `capture_start` usable with same token; same handle + different principal's token → denied (possession ≠ authorization); handle ops after token renewal (same `did`) succeed |
| B1–B3 (when they land) | `POST /mcp` without Bearer → 401 on **every** request (not just first); disallowed `Origin` → rejected; `aud=core` token rejected by MCP (`aud=mcp` required); GET/DELETE on `/mcp` → 405 |

#### wlanpi-webui — pytest

| Backs | Test cases |
|---|---|
| P9 | Every mutating route unauthenticated → redirect-to-login/401 (route walker like P10's, with an explicit anonymous allowlist — expected: login page + static assets only); mutating actions are `POST` and reject missing/invalid CSRF token; session idle-timeout expires; login failures rate-limited; `GET /startprofiler`-style anonymous service control is the named regression test |

#### Image-level smoke tests (pi-gen or hardware-in-loop, per image build rather than per PR)

| Backs | Check |
|---|---|
| P3 | From an off-box network namespace: with flags enabled, `:31416`/`:8767` answer HTTPS with the device cert; plain `:31415`/`:8766` cleartext unchanged until P3.1 (dual-stack window — test encodes current phase); UFW TLS profiles active when enabled |
| P1+P3 | End-to-end: `getjwt` on-box → Bearer call from off-box over TLS → 200; same call with revoked token → 401 |
| P9 | Anonymous fetch of a WebUI mutating route from off-box → login redirect |

Two rules to make this stick: **(1)** the static checks and the P10/P9 route walkers are the regression backstop — they catch the *next* engineer's unauthenticated route or nginx identity map without anyone remembering this document; **(2)** tests encode *current* policy, not aspiration — e.g. the secret-permissions test asserts 0640 until B5 deliberately changes it, so every tightening shows up as a reviewed test diff.

---

## 5. Could the full architecture be the direct Prague route?

Short answer: **it would not be a breaking change if sequenced with the compatibility rules below — the WLAN Pi app and the internal `getjwt` flow keep working throughout — but it roughly doubles the auth engineering for Prague while the extra items remove no classroom risk.** The deviation between the two tracks is scope and sequencing, not destination.

### 5.1 Impact of each beyond-Prague item on existing consumers

| Item | Breaking for the WLAN Pi app? | Breaking for internal HMAC clients (fpms, `getjwt`)? | Notes |
|---|---|---|---|
| P2 Token lifetime | No | No | Default `wall_clock_grace`: app tokens survive reboots within the 7-day window. Optional `boot_bound` tightens to monotonic uptime — opt-in via config, not the shipped default |
| P3 TLS front-ends | No | No | Off by default; enabling adds HTTPS on new ports only. Plain `:31415` stays until P3.1 |
| B1 Streamable HTTP for MCP | No | No | MCP-only; the app talks REST to core directly, never through MCP |
| B2 `aud` claims | **No, if lenient** | No | Rule: core *issues* `aud` going forward but *accepts* tokens without `aud` (legacy) at core endpoints. Only MCP enforces `aud=mcp`. Existing 7-day app tokens age out naturally; the app's next SSH `getjwt` run returns an `aud=core` token transparently — same command, same JSON shape |
| B3 Introspection endpoint | No | No | Purely additive |
| B4 Service identity + `did` assertion | No | No | Internal to the MCP→core hop; the app's direct Bearer path is untouched |
| B5 Secret → 0600 root-only | No | **No, with an audit** | `getjwt` is documented as `sudo getjwt`, so root-only is fine for it and for the app's SSH flow. Must audit anything reading the secret as group `wlanpi` before flipping (candidates: pairing proxies, any service unit running as `wlanpi`) |
| B6 Pairing flow | No | No | Additive; SSH+`getjwt` remains as fallback until the app adopts pairing |
| B7 Scopes | **No, if lenient** | No | Rule: tokens without a scope claim get full legacy rights; scoping becomes opt-in per issuance |

The one genuinely app-facing transition in either track is **retiring cleartext `:31415` on the LAN** — P3 adds optional TLS on **`:31416`** without touching HTTP `:31415`; P3.1 is the deliberate cutover (loopback-only HTTP + optional TLS on `:31415` via `WLANPI_CORE_TLS_API_PORT`). If LAN cleartext were switched off before the app trusts the device cert and speaks HTTPS, deployed clients break. Rule: dual-stack (HTTP `:31415` + HTTPS `:31416`) for at least one release cycle; P3.1's `WLANPI_CORE_HTTP_API=0` only after the WLAN Pi app update ships; internal HMAC/`getjwt` keep loopback HTTP.

### 5.2 Why the Prague slice still wins

- The classroom threat model (LAN sniffing, immortal tokens, no working revocation, blast radius) is fully addressed by P1–P8. B3/B4 defend against confused-deputy on a single-owner box — a non-risk until multi-party deployments exist.
- B4 (identity assertion) is the subtle piece: get it wrong and per-user attribution silently breaks. It deserves unhurried design, not a release-deadline implementation.
- B1 is gated on harness client support for Streamable HTTP, which is exactly the TBD decision.

**Cheap pull-forward worth taking:** B2's *issuance* side (mint `aud` claims now, enforce nowhere except MCP later) is a few lines in `create_token` and makes the later cutover a no-op. Everything else stays sequenced after Prague.

---

## 6. Relationship to issue #139

Recommendation: **keep #139 exactly as scoped** — it is a crisp, testable enabler (credential dispatch + sentinel removal) and P1 implements it verbatim. Post this document as a **new tracking issue** ("MCP auth & transport architecture — Prague and beyond"), referencing #139 as its first dependency, with §4.1 as the Prague checklist and §4.2 as the follow-on milestone. Widening #139 itself would delay its merge and blur its acceptance criteria.

---

## Appendix A — Streaming WS APIs: multi-listener rights and token interaction

Context: new WebSocket streaming APIs (starting with packet capture) may have **multiple concurrent listeners**, and one app may start a stream that another principal (e.g. MCP under the student's token) subscribes to. Open decision: is that cross-principal subscribe allowed, and under what rights?

### A.1 Model: streams are resources with an owner and a lifecycle

- Every stream/capture has an **owner = the `did` of the token that started it**, an id (`cap_abc`), and a lifecycle independent of any listener connection. Listeners joining or leaving never starts/stops the stream.
- Rights are evaluated **per operation**, not per connection:
  - `start` / `stop` / `reconfigure`: owner `did` only (later: or `admin` scope).
  - `subscribe` (read frames): policy decision, below.
  - `list`: any authenticated principal sees streams it may subscribe to.

### A.2 Subscribe policy options

| Policy | Behaviour | Fit |
|---|---|---|
| **A. Device-open reads** (Prague recommendation) | Any *valid authenticated* principal on this Pi may subscribe to any active stream; only the owner may stop/reconfigure. | Single-student-per-Pi: every token on the box belongs to the same human or their apps. Enables "WebUI starts capture, MCP listens" with zero ACL machinery. |
| B. Owner-only | Subscribe requires same `did` as owner. | Breaks the multi-app use case (WebUI `did` ≠ MCP client `did`); forces token sharing between apps, which is worse. |
| C. Per-stream ACL / grant | Owner grants read to named `did`s or "all". | Right long-term shape (B7 scopes can subsume it); too much machinery for Prague. |

Prague ships **A**, with the policy stated in docs; **C (or scope-based)** arrives with B7 for multi-user or higher-sensitivity deployments. Note the data-sensitivity angle: a classroom pcap contains *other students'* over-the-air traffic regardless of which principal reads it — device-open reads do not meaningfully widen that exposure on a one-owner device.

### A.3 Token presentation at the WS handshake

Browsers cannot set `Authorization` on WebSocket upgrades, so pick one deliberately:

- **Recommended:** first-message auth — connection opens, client's first frame is `{"type":"auth","token":"..."}`, server closes (4401) if not received within a short window. Works from every client type, keeps tokens out of URLs.
- Acceptable: `Sec-WebSocket-Protocol` token smuggling (works in browsers, slightly hacky).
- **Avoid query-string tokens:** the current nginx `json_combined` log format records the request line and body — tokens would land in `nginx_access.log`.

### A.4 Token lifetime vs connection lifetime

- Validate at subscribe time; the connection may then outlive the token's TTL until closed (a capture spanning token renewal must not drop). This is safe because subscribe rights were checked against a then-valid token, and the blast radius is read-only frames.
- **Revocation is the exception:** revoking a token should actively close that principal's listener sockets (core keeps `did` → active-connections map; the P2 cache-eviction fix should emit the event). If this is too much for Prague, document that revocation stops *new* subscriptions immediately and existing sockets persist until the stream ends.
- Ownership survives renewal automatically because it binds to `did` (§2.2) — a renewed token stops/queries yesterday's still-running capture without ceremony.

### A.5 MCP's consumption pattern (stateless-safe)

MCP tool calls are request/response; a spec-conformant stateless MCP server should not hold a WS open on behalf of one protocol session. Pattern:

1. `capture_start` → core creates stream, returns handle (`cap_abc`, owner = student's `did`).
2. MCP subscribes internally (as a listener like any other) and buffers/summarises.
3. `capture_frames(handle, cursor)` → MCP returns frames/summary since cursor; possession of the handle is **not** authorization — MCP re-checks `(handle, did-of-presented-token)` per call.
4. `capture_stop(handle)` → owner-checked at core.

Multiple listeners (WebUI live view + MCP summarizer + a future scandump consumer) attach to the same core stream; core owns fan-out and per-listener backpressure so one slow consumer cannot stall the capture.

### A.6 Decisions needed before P6 lands

1. Subscribe policy A vs C for Prague (recommendation: A).
2. Handshake auth mechanism (recommendation: first-message auth).
3. Revocation → active-socket close: Prague or beyond (recommendation: beyond, documented).
4. Whether `stop` needs an instructor override path before scopes exist (recommendation: no — `sudo` on the box is the override).

---

## Appendix B — Other access surfaces: the WebUI hole and third-party interfaces

Securing MCP is not enough if other doors stay open. This appendix covers the surfaces that are not MCP clients, states one governing principle, and shows that the architecture in this doc already accommodates them.

### B.1 The governing principle

> **Access is granted to principals presenting credentials — never to locations, and never implicitly through intermediaries.** Any interface that fronts core must either (a) have its users present their own core credential, or (b) authenticate its users itself and assert the authenticated identity downstream. An intermediary that holds a privileged credential *without* authenticating its own front door is a confused deputy.

#139 applies this principle to *where the request comes from*. This appendix applies it to *who is asking through whom*. MCP passthrough, the nginx sentinel, and the WebUI hole below are all the same bug wearing different clothes.

### B.2 The live hole: WebUI as an unauthenticated confused deputy

Verified against the current wlanpi-webui codebase:

- `wlanpi_webui/utils.py` reads core's `shared_secret.bin` (readable because the WebUI runs in the `wlanpi` group — §1.2 defect 1) and HMAC-signs core API requests **on behalf of any browser visitor**.
- There is **no login, session, or auth of any kind** in the WebUI. (The front door is anonymous; Cockpit and Grafana, by contrast, have their own logins.)
- Concrete anonymous capabilities today: `GET /startprofiler` / `GET /stopprofiler` start and stop services through core's system API under the privileged HMAC identity; `/profiler/<filename>` serves capture/profile artifacts to anyone; further blueprints proxy network/stream data.
- Bonus defect: mutating actions are plain `GET`s — even after login exists, they need to become `POST` + CSRF token, or any authenticated student can be CSRF'd by a hostile web page.

Impact in the classroom model: any student (or anything on the LAN) can manipulate any other student's Pi through its WebUI, regardless of how well MCP and the API are secured. **TLS does not help — the requests are legitimate, just anonymous.**

### B.3 Locking down the WebUI

| Option | Shape | Assessment |
|---|---|---|
| **1. Server-side session login** (recommended) | Flask login page → session cookie; credential = PAM (same account as SSH/Cockpit) or a device password set at first boot / first WebUI visit. WebUI keeps calling core (HMAC now; + identity assertion when B4 lands; per-user scoped token under B7). Mutating routes become `POST` + CSRF. | Smallest change that closes the hole; consistent with Cockpit's PAM precedent; browser never holds an API token. **Prague candidate (P9).** |
| 2. Browser as first-class API client | WebUI becomes a static app; the browser obtains its own core JWT (pairing/login endpoint) and calls `:31415` directly with Bearer + CORS. | Cleanest trust model — WebUI leaves the privileged class entirely and becomes "just another token-holding app" (§1.4). Larger rework; token-in-browser XSS surface to manage. Natural **beyond-Prague evolution (B9)** as the WebUI is modernised. |
| 3. Auth at nginx (basic auth / OIDC in front) | nginx gates `:443`. | Rejected: repeats the auth-in-nginx anti-pattern (#135's lesson, §2.1 of the sitrep analysis), gives core no per-user identity, and doesn't fix CSRF/GET-mutation. |

Session semantics for option 1 mirror §2.2: the browser session cookie is short-lived (idle timeout ~hours); the durable identity is the device account. This is exactly the "session login" instinct in the requirement — a session *at the interface that owns the human*, not a protocol session at core.

### B.4 Third-party interfaces ("anyone can build one")

Today the barrier is accidental: any process running as user/group `wlanpi` can read the shared secret and become fully privileged; anything else must get a token via `getjwt`. The target makes the barrier deliberate:

1. **B5 (secret → root-only, provisioned per-service credentials)** is the linchpin: after it, *no* new interface can silently join the privileged class by virtue of its Unix user. Every new interface must pair (B6) for its own `did`-bound token.
2. **B7 scopes** bound what a paired interface may do (`read` vs `capture` vs `admin`), so "easily built" interfaces are least-privileged by default rather than all-powerful.
3. **Per-`did` rate limiting and audit** (already in core's design) make every interface individually attributable and revocable.
4. **P10 guard rail** keeps the core side deny-by-default: a CI test fails if any route lacks an auth dependency and is not on an explicit, reviewed public allowlist (candidate allowlist: nothing, or at most an unauthenticated device-identity/health endpoint for discovery).

With these, the answer to "someone built a rogue web frontend for the Pi" becomes: it can only do what its paired, scoped, revocable token allows — and if it didn't pair, it can do nothing.

### B.5 Adjacent front doors (noted, out of scope here)

Cockpit (PAM login) and Grafana (own login) already authenticate. Kismet and librespeed are proxied by the WebUI and inherit whatever front-door auth the WebUI gains in P9. The capture WS is Appendix A. The only other unauthenticated core surface is the OTG stub (§1.2 defect 4), removed in P1.

### B.6 Decisions needed

1. Is P9 (WebUI session login) in Prague scope? (Recommendation: yes — it is the largest *currently exploitable* hole in the classroom threat model, bigger than anything MCP-related.)
2. Login credential for the WebUI: PAM reuse vs dedicated device password? (Recommendation: PAM — one credential story per device, same as SSH/Cockpit.)
3. Public allowlist content for P10: empty, or a minimal identity/health endpoint?
