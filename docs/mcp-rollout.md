# MCP rollout — master plan (internal locked, external documented)

Action-oriented companion to the design in [`mcp-auth-plan.md`](./mcp-auth-plan.md).
It says what is **done**, what **locks internal on-box MCP**, and what is **left
for external/remote MCP**. Capture-specific contract: [`capture-ws-mcp-handover.md`](./capture-ws-mcp-handover.md).

## 1. What has landed (core branches, building/passing)

| Branch (PR) | Delivers |
|---|---|
| `feature/token-hardening` (#159, P2) | Immediate revocation; boot-bound monotonic token lifetime; `TOKEN_LIFETIME_MODE` (default `wall_clock_grace`) |
| `feature/credential-auth-dispatch` (#160, P1/#139) | Auth dispatched on the credential presented; `X-Wlanpi-Client` sentinel removed; route-auth guard-rail test |
| `feature/tls-frontends` (#162, P3) | Feature-flagged nginx TLS front-ends (`:31416` API, `:8767` MCP, `:8443` dev); capture WS proxied over `wss://`; UFW; `nginx -t` tested |
| `feature/capture-auth` (#165, P6) | Capture WS first-message auth (4401), `did`-owned sessions, read-only subscribers, namespace-aware capture, `ws://` nginx proxy; reference harness; handover doc |
| wlanpi-mcp `feature/drop-client-tag` | MCP sends a plain Bearer (no sentinel) — depends on P1 |

**Merge order into `dev`, then rebuild the integration image once:** #159 → #160 → #162 → #165. They are largely independent; this order keeps auth (P1) and tokens (P2) landing before the branches that assume them.

## 2. Internal / on-box MCP — LOCKED once the four PRs merge

On-box MCP (stdio, or loopback HTTP) reaches core over `localhost:31415`. That path is complete:

- **Auth:** #139 lets MCP present a plain Bearer from localhost (no sentinel). First-message token auth secures the capture WS.
- **Tokens:** P2 gives working revocation + lifetime. On-box MCP over loopback **needs no TLS** — Bearer + P6 WS auth is enough.
- **Capture:** `ws://localhost:31415/api/v1/streaming/capture` works through nginx (WS upgrade proxied). MCP can own a capture or subscribe by interface.

**Remaining to make it useful (wlanpi-mcp repo, against the handover doc + harness):**

| Item | Repo | Note |
|---|---|---|
| **P7** capture tools (owner: start/status/frames/stop; subscribe-by-interface via `list_sessions`) | wlanpi-mcp | Contract = `capture-ws-mcp-handover.md`; dissection reference = the harness |
| **P5** token-from-env only; drop `X-Wlanpi-Client`; loopback/HTTPS docs | wlanpi-mcp | Depends on P1 being on the box |
| **P4** `getjwt --export` / `--write-env` | wlanpi-core | So agents/instructors never paste a JWT into config |

When these land, internal MCP capture is production-usable for a single-operator box.

## 3. External / remote MCP — DOCUMENTED, not yet closed

Remote MCP (Cursor/Claude on a laptop → device) is the **same capture protocol plus transport + trust**, not a different design. What it needs:

| Item | Owner | Status |
|---|---|---|
| Enable TLS on the device (`wlanpi-core-tls enable api`, + MCP TLS if MCP is HTTP on-box) | operator/image | nginx **done**; feature-flagged off by default |
| Clients use `wss://wlanpi.local:31416/...` and **trust the device cert** | client | Cert SAN covers `wlanpi.local` + loopback, **not** the LAN IP/hostname → connect by `wlanpi.local` (mDNS) or distribute/TOFU the cert |
| **MCP daemon binds loopback** when its TLS front is enabled | wlanpi-mcp packaging | Today binds `0.0.0.0:8766`; loopback is a *manual* step — should become the package default |
| **P8** one-page student setup (token env + cert trust + harness/client choice) | docs | Not started |
| Cert SAN regeneration / pairing UX (SAN for current IPs, or TOFU flow) | wlanpi-core | The real external gap; PKI, not nginx |

nginx transport for external is **complete** (`wss://` capture + TLS fronts). The external blockers are **cert/trust + MCP bind-to-loopback + setup UX**, not nginx.

## 4. Beyond Prague (spec-correct remote MCP) — B-track, after the above

Only needed when the box is **multi-party / multi-tenant** (confused-deputy matters). Not required for a classroom where one teacher owns the box.

- **B1** Streamable HTTP (`POST /mcp`, stateless) for wlanpi-mcp
- **B2** `aud` claims (issue now, enforce later — cheap pull-forward)
- **B3** core introspection endpoint (HS256 → no JWKS)
- **B4** MCP service identity to core — **ends JWT passthrough**
- Busy/interference detection + `GET /wifi/capture/sources` (`busy` flag) — parallel enhancement, natural home for the busy check
- Optional nginx consolidation: single `443` vhost with `/api` + `/mcp` paths instead of separate ports

## 5. Recommended sequence

1. Merge #159 → #160 → #162 → #165; refresh the integration build.
2. Tidy the last status text (handover §6 + harness done on `feature/capture-auth`; this doc + plan P3/P6 done on `docs/mcp-auth-plan`).
3. wlanpi-mcp: **P5 + P7** (stdio/loopback first) — this is the shortest path to useful on-box capture.
4. **P4** `getjwt --export` in core.
5. External: enable TLS + cert trust + **P8** setup page; make MCP loopback-bind the default.
6. B1–B4 + SAN/pairing + busy detection only when remote/multi-tenant matters.

**Bottom line:** internal on-box MCP is locked once the four PRs merge and wlanpi-mcp implements P7/P5 against the harness. External is the same capture protocol plus TLS enablement, cert/token UX (P3/P4/P8), and MCP loopback-bind — no new capture protocol, no remaining blocking nginx work.

## 6. Tracking hygiene (open, not blocking)

- Upstream PRs #158–#160, #162, #165 open.
- Org issue for the `dbus-python` sbuild flake never filed (403 on create) — body drafted; file when access allows. It is a transient index/network flake, not a code regression (P1–P3 don't touch deps).
- Session todos: P6 done; #157 (first-boot) / #155 (stale MCP gaps) are from the older sitrep and unrelated to MCP capture.
- P9 (WebUI anonymous-access auth) and P10 (route-auth guard rail) are separate product-risk items; P10 is covered by the #139 route-walker test.
