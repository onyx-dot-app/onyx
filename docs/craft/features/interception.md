# Egress Interception & Secrets

## Objective

Give the Craft sandbox a way to call external services — Linear, HubSpot, GitHub, internal APIs — without ever seeing the credentials and without ever performing an external write that nobody approved. Today the sandbox either has no path to external systems at all, or (if a skill author hardcodes a token) has a raw API key sitting in environment variables alongside the agent's bash tool. Neither is acceptable for an enterprise product.

V1 introduces an Onyx-managed egress proxy. All sandbox HTTP/HTTPS traffic is routed through it via standard `HTTP_PROXY`/`HTTPS_PROXY` env vars; the sandbox image trusts an Onyx-generated CA so the proxy can MITM TLS. Skills call upstream URLs in the normal way (`https://api.linear.app/graphql`); the proxy resolves the request to a registered service, classifies it (read / write / delivery / destructive / unknown), injects credentials server-side for allowlisted requests, and forwards. Writes that are policy-gated pause the request, raise an approval, and replay on approve. The sandbox never receives a raw token, ever.

This is also the enforcement point for project #6 (Approvals) and the substrate that project #5 (OAuth for External Apps) layers per-user tokens onto.

## Issues to Address

1. **No way to give the sandbox external reach without leaking secrets.** Skill authors today have to either skip external integrations entirely or stash an API key in the sandbox image / session env. The agent's bash tool can `cat $LINEAR_API_KEY` whenever it wants — and so can any prompt-injection vector that reaches the agent.
2. **No first-line enforcement of "writes need approval."** Even with great prompting, the agent can be coerced or convinced to call an upstream `POST /issues` directly. Approval enforcement at the prompt layer is best-effort guidance; the actual bytes go on the wire whenever the tool fires. We need an Onyx-controlled boundary that physically intercepts the request before it leaves the deployment.
3. **Two parallel external-call paths today.** Onyx custom tools call upstreams from the main app with OAuth/API-key injection (`backend/onyx/tools/tool_implementations/custom/custom_tool.py`). Federated connectors do the same from their own modules (`backend/onyx/db/federated.py`). Neither runs from inside the sandbox — both are server-side calls invoked from chat. Craft skills need their own path because they run inside the sandbox process, but we should not invent a third credential model.
4. **No classification of upstream requests.** "API call" is one bucket today. We need to distinguish reads (`GET /issues`) from writes (`POST /issues`) from deliveries (`POST /messages`, `POST /emails`) from destructive operations (`DELETE /repo`) so policy can attach to the dangerous ones without bottlenecking the safe ones.
5. **No audit of which upstreams a session actually called.** When a Craft trigger runs overnight and the customer asks "what did it do?", we want a precise list (HubSpot at 02:14, two reads; Linear at 02:15, one write — approved by user X) — not a guess from prompt logs.

## Important Notes

- **The proxy is a security-critical, single-purpose component.** It is the only place in the deployment that decrypts external-service secrets, and the only enforcement point for "this write needs approval before it goes out." Treat its surface area like an authentication boundary: small, dedicated, well-tested, restartable independently of the rest of Onyx.
- **HTTP_PROXY interception, not a transparent network appliance.** Self-hosted admins should not need to reconfigure iptables, run a sidecar with `NET_ADMIN`, or own a CNI plugin to use Craft. We use the standard `HTTPS_PROXY` env var supported by every HTTP library the sandbox runs (Node fetch, Python `requests`/`urllib3`/`httpx`, `curl`, `git`). The trade-off — software that explicitly bypasses `HTTPS_PROXY` (rare) escapes interception — is acceptable for V1; we mitigate by also blocking direct egress at the network layer where the backend supports it (Docker network policy, K8s NetworkPolicy) so non-proxy traffic is dropped, not silently allowed.
- **TLS MITM via an Onyx-generated CA.** The proxy generates its own root CA at first boot, signs leaf certs on demand for each `CONNECT` target, and the sandbox image trusts that root via `/usr/local/share/ca-certificates/`. Node and Python pick it up via `NODE_EXTRA_CA_CERTS` and `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` env vars set in the sandbox. The CA private key is encrypted at rest with the existing Onyx encryption key (`ENCRYPTION_KEY_SECRET`), regenerated only on explicit admin reset.
- **Sandbox never sees decrypted secrets.** This is not a goal we can soften under any circumstance. The proxy is the only process that calls `decrypt_bytes_to_string` for `CraftSecret` rows. Secrets do not pass through the api_server, the sandbox, the agent, or any artifact. The sandbox's view of the world is "I called `https://api.linear.app/graphql` and got `200 OK`."
- **Non-secret internet access defaults to pass-through.** Settled in the main plan. If the sandbox wants to `curl https://example.com/index.html` for a public URL, the proxy lets it through with no credential injection. We do not become an internet allowlist by default. (Admins can flip a `block-by-default` deployment flag if they want lockdown; not the default.)
- **Reuse, don't fork, the existing OAuth machinery.** `OAuthConfig` and `OAuthUserToken` already store encrypted client credentials and per-user tokens for custom tools (`backend/onyx/db/models.py:3357,3401`). They are the basis for project #5 (OAuth Apps). Project #4 — this doc — handles the **org-wide secret** case (an API key shared across all Craft sessions for a tenant); it does not duplicate the per-user OAuth machinery, it pre-builds the proxy resolver in a way that project #5 layers per-user tokens onto cleanly.
- **Classification is per-service, not per-request, in V1.** Each `CraftInterceptedService` carries its own simple classification rules — by HTTP method, URL path prefix, GraphQL operation name. The proxy applies them at request time and tags the request as `READ` / `WRITE` / `DELIVERY` / `DESTRUCTIVE` / `UNKNOWN`. We do not attempt to deep-parse arbitrary upstream APIs. `UNKNOWN` defaults to "treat as write" — opinionated and safe; admins can override per service.
- **`UNKNOWN` requires approval by default.** If we don't know what a request does, we don't let it through unattended. The exception is internal/non-secret destinations (no service registered) — those default to pass-through, as above.
- **Approvals enforcement lives here.** When the proxy classifies a request as a category that requires approval (per the service's `approval_policy`), it pauses the request, opens an approval record (project #6), and either returns a synthetic 202-style response to the sandbox or holds the connection open until decision. The proxy holds an encrypted snapshot of the original request (URL, headers minus auth, body, idempotency key) so it can replay byte-for-byte after approval — without re-deriving the agent's intent. Snapshots are short-lived (configurable; default 24h) and encrypted with `ENCRYPTION_KEY_SECRET`.
- **Idempotency keys are mandatory for write replay.** When a request is paused for approval, the proxy stamps an idempotency key into the snapshot. On approval, the proxy sets the upstream-appropriate idempotency header (`Idempotency-Key`, `X-Idempotency-Key`, etc.) per the service definition, so retries don't double-write. Writes that we've classified but for which the upstream has no idempotency support are flagged in the service definition (`supports_idempotency = false`) and approved-and-replayed at the user's risk; those services are surfaced in the admin UI with a "no idempotency" badge.
- **Per-tenant grants are explicit.** A `CraftInterceptedService` is registered by an Onyx admin and gated by a `CraftInterceptedServiceGrant` (org-wide, group, or user). Sandbox sessions inherit the calling user's grants. Self-hosted single-tenant deployments mostly use org-wide grants; multi-tenant cloud deployments will lean on per-group or per-user.
- **Audit is project #9, not this project.** This doc emits structured events at every interesting transition (request received / classified / injected / approved / replayed / denied / passed-through). Persistence and admin queries belong to the run-audit project. Don't replicate that work here.
- **Local sandbox backend bypasses the proxy.** `local` mode is dev-only and runs on the host. Routing it through the proxy adds operational complexity for self-hosted dev laptops without security value (the agent is already running as the api_server user — the secret leak threat model doesn't apply). Keep `local` direct; require `docker` or `kubernetes` for production Craft.
- **No backwards compatibility.** Per the main plan, V1 has no migration story for existing Craft state. If a skill author shipped a hardcoded token in an attachment, that token works once, won't work after the next session bootstrap, and the admin sees it called out in the egress logs.

## Approaches Considered

### A. Inject credentials at the tool layer in the main app (rejected)

Keep external-API calls in the main app the way custom tools do today; expose them to the sandbox as Onyx-side HTTP endpoints. The sandbox calls `POST /api/build/sandbox/external/linear/issues` instead of `POST https://api.linear.app/graphql`. The api_server holds the secret and forwards.

**Why rejected:** It re-implements every upstream API as a typed Onyx route. Skill authors lose the ability to call any upstream directly — they can only call what we've shimmed. Skill portability with the broader Codex/OpenCode ecosystem (a stated goal of project #3) breaks immediately, because their skills assume real upstream URLs. We'd be building a service mesh's worth of bespoke routes for no security gain over a transparent proxy.

### B. Transparent network appliance with iptables / eBPF redirection (rejected)

Run a sidecar with `NET_ADMIN` capability that DNATs all egress through the proxy regardless of `HTTP_PROXY`. Catches every TCP connection.

**Why rejected:** Operationally heavy for self-hosted (the docker backend would need a privileged sidecar; Linux kernel/network stack assumptions vary across distros and Docker Desktop). Cloud K8s gets it via NetworkPolicy + service mesh, but that doesn't help self-hosted compose users who are the bigger pain point. The marginal security win — catching software that explicitly bypasses `HTTPS_PROXY` — is real but small; almost nothing the agent runs does that. We can re-evaluate after V1 if we see a concrete bypass case in production.

### C. Per-upstream sidecars (rejected)

A pattern where each registered upstream gets its own small process (e.g. a "Linear sidecar") that the sandbox calls, which forwards to Linear with the secret injected.

**Why rejected:** Doesn't scale. Every new service is a new process, deployment, healthcheck, and version. Centralizing classification and approval logic gets harder, not easier. Tools like `kong` or per-service `envoyfilter` exist for a reason in larger environments, but they're way more infra than a 5-person team running self-hosted Onyx wants.

### D. mitmproxy-based forward proxy in the Onyx monorepo (winner)

A new in-monorepo Python service, `onyx-craft-egress`, built on `mitmproxy`'s [proxy library](https://docs.mitmproxy.org/) (specifically the `mitmproxy.proxy` and `mitmproxy.addons` machinery — not the interactive UI). Listens for `CONNECT`-style HTTPS traffic from the sandbox, terminates TLS using a leaf cert signed by the Onyx-generated CA, classifies the request against `CraftInterceptedService` rules in Postgres, optionally injects credentials from `CraftSecret` rows, forwards upstream, streams the response back. Approval-gated requests pause via the standard mitmproxy intercept hook and resume on approval.

**Why this wins:**
- **`HTTP_PROXY`/`HTTPS_PROXY` is universal.** Every HTTP runtime in the sandbox respects it (`fetch`, `node-fetch`, `axios`, `requests`, `httpx`, `urllib3`, `curl`, `git`, `pip`, `npm`). One env var pair and we're intercepting the world the agent actually uses.
- **`mitmproxy` is the canonical, well-audited Python implementation of TLS MITM.** It owns the awkward parts: per-host leaf cert generation, ALPN negotiation for HTTP/2, CONNECT semantics, websocket passthrough. We get those for free and write only Onyx-specific addons (resolver, classifier, injector, approver).
- **Same monorepo, same encryption key, same Postgres.** No new protocol between this proxy and the api_server — it reads `CraftInterceptedService` and `CraftSecret` directly from the same DB (with a small read-only connection pool). Echoes the "skip the indirection" call from the docker-backend doc.
- **Process-level isolation.** Runs as its own service in compose / its own deployment in helm, so its blast radius is small and it can be restarted without touching api_server. Different reliability and security profile than the api_server warrants — the proxy must not crash on a malformed sandbox request and must not leak between concurrent requests.
- **Approval gating fits the mitmproxy lifecycle naturally.** mitmproxy already exposes a per-flow `intercept`/`resume` API that we use to pause requests pending approval — no exotic state machine.
- **Future upgrade path.** If we ever want eBPF / transparent interception (approach B) or a multi-tenant gateway, we can keep the same `CraftInterceptedService` + `CraftSecret` data model and swap the listening surface. The DB schema is the contract.

## Key Design Decisions

1. **`onyx-craft-egress` is a new service in the monorepo.** Code lives at `backend/onyx/craft/egress_proxy/`. Started by the same Python entrypoint pattern as the api_server (`python -m onyx.craft.egress_proxy`). One process, asyncio-based, listens on a single configurable port (default `8444`).
2. **mitmproxy as a library, not a CLI.** We import `mitmproxy.proxy.master`, `mitmproxy.proxy.config`, and the addon hook surface; we do not run `mitmproxy`/`mitmweb`/`mitmdump`. Onyx writes a small set of addons (resolver, classifier, injector, approver, audit emitter) and registers them with the master. Pinned to a specific mitmproxy version.
3. **Onyx-generated CA, encrypted at rest.** On first boot, the proxy generates a 4096-bit RSA root CA, encrypts the private key with the existing `ENCRYPTION_KEY_SECRET` Fernet key, and stores both the encrypted key and the public cert in a new `CraftEgressCA` table (singleton row per tenant). Leaf certs for upstream hosts are generated on demand and held in an LRU cache keyed by SNI. The CA cert is exposed at a sandbox-only endpoint (`GET /api/build/sandbox/egress/ca.pem`, authenticated by the session token from project #1 in `search-design.md`) so `setup_session_workspace` can fetch and install it; for image-baked deployments where the CA is stable, it's also written into the sandbox image at build time.
4. **Sandbox setup writes proxy env vars.** `setup_session_workspace` (in each `SandboxManager`) sets:
   - `HTTPS_PROXY=http://onyx-craft-egress:8444`
   - `HTTP_PROXY=http://onyx-craft-egress:8444`
   - `NO_PROXY=localhost,127.0.0.1,api_server,<onyx-internal-hosts>` (so the sandbox can reach the api_server for `company_search` etc. without round-tripping through the proxy)
   - `NODE_EXTRA_CA_CERTS=/etc/ssl/certs/onyx-craft-ca.crt`
   - `REQUESTS_CA_BUNDLE=/etc/ssl/certs/onyx-craft-ca.crt`
   - `SSL_CERT_FILE=/etc/ssl/certs/onyx-craft-ca.crt`
   The CA cert file is materialized into the session workspace (or baked into the image) before the OpenCode process starts.
5. **Sandbox auth to the proxy is the existing session token.** The proxy expects a `Proxy-Authorization: Bearer <ONYX_BUILD_SESSION_TOKEN>` header on every CONNECT/request. (`HTTP_PROXY` libraries forward the env var `HTTPS_PROXY=http://user:token@host:port` and add the Proxy-Authorization header automatically; we use the form `http://session:<TOKEN>@onyx-craft-egress:8444`.) The proxy resolves token → `BuildSession` → `User` → tenant exactly the way the search endpoint does (`require_sandbox_session_token` from project #1). Requests without a valid token are rejected with `407 Proxy Authentication Required`.
6. **Service resolution is host-prefix-based, deterministic.** When the proxy sees a request to `https://api.linear.app/graphql`, it looks up `CraftInterceptedService` rows whose `upstream_hosts` includes `api.linear.app`. Most-specific match wins (exact host > suffix wildcard `*.atlassian.net`). If no service matches, the request is treated as **non-secret pass-through** (no injection, no approval — but still logged and TLS-MITM'd for visibility, configurable per-deployment).
7. **Classification is rule-based per service.** Each `CraftInterceptedService` carries an inline `classification_rules` JSONB list. A rule is a conjunction of: `method` (HTTP verb), `path_pattern` (glob), optional `body_match` (a JSONPath + regex pair, used for GraphQL operation classification), and a `category` (`READ`/`WRITE`/`DELIVERY`/`DESTRUCTIVE`). First match wins. No match → `UNKNOWN`. Built-in services (Linear, HubSpot, GitHub, etc.) ship with a curated rule set; custom services start with a permissive default the admin can tighten.
8. **Approval policy is `category → mode`.** A service's `approval_policy` JSONB is a mapping like `{"READ": "allow", "WRITE": "approve_unless_owner", "DELIVERY": "approve_always", "DESTRUCTIVE": "approve_always", "UNKNOWN": "approve_always"}`. Valid modes: `allow` (no approval), `approve_unless_owner` (auto-approve if the session's owner is acting interactively, approve for triggers and others), `approve_always`, `deny` (never run). Admin defaults are sensible for built-in services and editable.
9. **Approvals integrate via a single intercept hook.** The proxy's `approver` addon, when it sees a request that needs approval, calls `craft_approvals.create_request(session_id, snapshot, category)` from project #6. That function returns a future-like handle; the addon awaits it with a per-service timeout (default 1h, configurable) and either resumes the flow on approve or returns a structured `403 Approval Denied` payload to the sandbox. The flow is held on the proxy side; the sandbox sees a long-running HTTPS request, no exotic protocol.
10. **Snapshot for replay is encrypted, short-lived, and minimal.** Stored in a new `CraftEgressApprovalSnapshot` table: `(approval_id, encrypted_request_body, content_type, idempotency_key, expires_at)`. URL, method, and host are kept on the parent approval record (not encrypted, used for the UI). Headers are sanitized — auth headers stripped before storage, since they'll be re-derived on replay. TTL default 24h; expired snapshots are rejected on replay even if the approval is still pending. Cleanup runs on the standard celery `light` worker.
11. **Direct external egress is blocked at the backend level when possible.** Docker backend: the sandbox container joins only the `onyx_craft_sandbox` bridge network (already proposed in `sandbox-backends.md`); the proxy is on that network, the public internet is not. Outbound traffic to anything other than the proxy fails at TCP. Kubernetes backend: a `NetworkPolicy` on the sandbox namespace allows egress only to the egress-proxy service. `local` backend: no enforcement (dev only). This belt-and-suspenders approach catches `HTTPS_PROXY`-bypass attempts.
12. **Audit emission is structured.** The proxy emits one event per request lifecycle transition: `received`, `resolved`, `classified`, `gated`, `approved`/`denied`, `injected`, `forwarded`, `responded`, `passthrough`. Events are written to a Postgres outbox table the audit project consumes. The proxy never logs request bodies or response bodies; it logs URLs (with query-string params hashed for cardinality control), categories, and decision metadata.

## Architecture

```
┌────────────────────── Sandbox (docker container / k8s pod) ──────────────────────┐
│                                                                                  │
│   OpenCode agent + skills                                                        │
│      │                                                                           │
│      │  e.g. curl -X POST https://api.linear.app/graphql ...                     │
│      │  honors HTTPS_PROXY env var                                               │
│      ▼                                                                           │
│   HTTPS_PROXY=http://session:<TOK>@onyx-craft-egress:8444                        │
│   Trusts /etc/ssl/certs/onyx-craft-ca.crt                                        │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │ CONNECT api.linear.app:443
                                   │ + Proxy-Authorization: Bearer <session token>
                                   ▼
┌──────────────────────── onyx-craft-egress (new service) ─────────────────────────┐
│                                                                                  │
│   mitmproxy.proxy.master   ┌─ session-token resolver  ──┐                        │
│        │                   │   token → session, user,  │                        │
│        ▼                   │   tenant, grants          │                        │
│   addons:                  └────────────────────────────┘                        │
│     1. resolver  ──────►  CraftInterceptedService lookup (Postgres, RO)          │
│     2. classifier ─────►  match classification_rules → category                  │
│     3. approver  ──────►  if approval needed: snapshot + craft_approvals.create_request
│                              await decision (or timeout)                         │
│     4. injector  ──────►  decrypt CraftSecret, set Authorization / custom header │
│     5. forwarder ──────►  upstream (real TLS via outbound httpx client)          │
│     6. audit     ──────►  outbox: events for project #9                          │
│                                                                                  │
│   Onyx CA (encrypted at rest in CraftEgressCA singleton row)                     │
│   Per-host leaf cert cache (LRU, in-memory)                                      │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │ TLS to api.linear.app
                                   ▼
                            ┌─────────────────┐
                            │ External API    │
                            └─────────────────┘
```

### Per-request flow (write, approval-gated)

```
sandbox                   egress proxy                      approvals (project #6)
   │                            │                                    │
   │ CONNECT api.linear.app:443 │                                    │
   ├───────────────────────────►│                                    │
   │ ... TLS handshake (leaf signed by Onyx CA) ...                  │
   │                            │                                    │
   │ POST /graphql {...mutation create issue...}                     │
   ├───────────────────────────►│                                    │
   │                            │ classify → WRITE                   │
   │                            │ snapshot request, idempotency key  │
   │                            ├──── create_request ───────────────►│
   │                            │                                    │ (UI prompt
   │                            │                                    │  → user approve)
   │                            │◄────────── approved ───────────────│
   │                            │ inject Authorization, replay       │
   │                            ├─── upstream POST ───►  Linear API  │
   │                            │◄─── 201 {...} ──────                │
   │ 201 {...}                  │                                    │
   │◄───────────────────────────│                                    │
```

## Data Model Changes

All new tables live alongside existing Craft/Build models (`backend/onyx/db/models.py`), seeded by a new alembic migration. No changes to existing tables in this project (a `craft_token` column is needed but is added by project #1 — search).

```python
class CraftEgressCA(Base):
    """Singleton (per-tenant) CA used to MITM sandbox TLS."""
    __tablename__ = "craft_egress_ca"
    id: Mapped[int] = mapped_column(primary_key=True)
    cert_pem: Mapped[str]                                  # public, plain
    encrypted_key_pem: Mapped[SensitiveValue[str]] = mapped_column(EncryptedString())
    created_at, updated_at, rotated_at, fingerprint: ...

class CraftInterceptedService(Base):
    __tablename__ = "craft_intercepted_service"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)         # e.g. "Linear"
    slug: Mapped[str] = mapped_column(unique=True)         # e.g. "linear"
    upstream_hosts: Mapped[list[str]] = mapped_column(JSONB)  # ["api.linear.app"]
    auth_scheme: Mapped[CraftAuthScheme]                   # API_KEY | BEARER | HEADER | HMAC | NONE
    auth_template: Mapped[dict] = mapped_column(JSONB)     # e.g. {"header":"Authorization","value":"Bearer {{secret}}"}
    classification_rules: Mapped[list[dict]] = mapped_column(JSONB)
    approval_policy: Mapped[dict] = mapped_column(JSONB)   # category -> mode
    supports_idempotency: Mapped[bool]
    idempotency_header: Mapped[str | None]                 # e.g. "Idempotency-Key"
    is_built_in: Mapped[bool]                              # seeded vs admin-created
    enabled: Mapped[bool]
    created_at, updated_at: ...

class CraftSecret(Base):
    """Org-wide secret material for an intercepted service."""
    __tablename__ = "craft_secret"
    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("craft_intercepted_service.id"))
    name: Mapped[str]                                      # e.g. "default" or "publish"
    encrypted_value: Mapped[SensitiveValue[str]] = mapped_column(EncryptedString())
    last_rotated_at: Mapped[datetime | None]
    created_at, updated_at: ...
    __table_args__ = (UniqueConstraint("service_id", "name"),)

class CraftInterceptedServiceGrant(Base):
    __tablename__ = "craft_intercepted_service_grant"
    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("craft_intercepted_service.id"))
    scope_type: Mapped[CraftGrantScope]                    # ORG | GROUP | USER
    scope_id: Mapped[UUID | None]                          # null for ORG
    approval_policy_override: Mapped[dict | None] = mapped_column(JSONB)  # optional per-grant override
    created_at, updated_at: ...

class CraftEgressApprovalSnapshot(Base):
    __tablename__ = "craft_egress_approval_snapshot"
    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("craft_approval.id", ondelete="CASCADE"))
    method: Mapped[str]
    url: Mapped[str]                                       # not encrypted (UI shows it)
    encrypted_body: Mapped[SensitiveValue[bytes]] = mapped_column(LargeBinary)
    content_type: Mapped[str]
    idempotency_key: Mapped[str]
    expires_at: Mapped[datetime]
    created_at: ...
```

`CraftAuthScheme`, `CraftGrantScope`, and the egress event categories are new enums in `backend/onyx/db/enums.py`. The audit event outbox table is owned by project #9 (`audit.md`), not added here.

## API Specs

### Admin (under `/api/admin/craft/intercepted-services`, cookie-authenticated, admin-only)

```
GET  /api/admin/craft/intercepted-services
        → list of services (with grant + secret summary, no decrypted values)

POST /api/admin/craft/intercepted-services
        body: { name, slug, upstream_hosts, auth_scheme, auth_template,
                classification_rules, approval_policy, supports_idempotency,
                idempotency_header, enabled }
        → 201 with the created service id

PATCH /api/admin/craft/intercepted-services/{id}
        body: any subset of the above fields
        → 200

DELETE /api/admin/craft/intercepted-services/{id}
        → 204 (cascades grants and secrets)

POST /api/admin/craft/intercepted-services/{id}/secrets
        body: { name, value }   # value is the raw secret; encrypted on write
        → 201

POST /api/admin/craft/intercepted-services/{id}/secrets/{secret_id}/rotate
        body: { value }
        → 200

DELETE /api/admin/craft/intercepted-services/{id}/secrets/{secret_id}
        → 204

POST /api/admin/craft/intercepted-services/{id}/grants
        body: { scope_type, scope_id?, approval_policy_override? }
        → 201

DELETE /api/admin/craft/intercepted-services/{id}/grants/{grant_id}
        → 204

POST /api/admin/craft/intercepted-services/{id}/test
        body: { method, path, sample_body? }
        → { matched_service: {id, slug}, classification: "WRITE",
            would_inject: true, would_require_approval: true }
        # Dry-run a request through resolver+classifier without forwarding.
```

### Sandbox-side (under `/api/build/sandbox/egress`, session-token-authenticated)

```
GET /api/build/sandbox/egress/ca.pem
        → text/plain PEM of the Onyx CA cert. Cached aggressively.
        # Used by setup_session_workspace if the sandbox image isn't pre-baked
        # with the cert (e.g. when the admin rotated the CA after image build).

GET /api/build/sandbox/egress/services
        → list of available services for this user, with display metadata
          (name, slug, base host(s), category labels). No secret material.
        # Used by skills/SKILL.md generation to advertise available upstreams
        # to the agent.
```

### Egress proxy listener

```
PROXY  any URL
        Proxy-Authorization: Bearer <session token>
        # Standard HTTP CONNECT and direct-HTTP forms; not a typed Onyx route.
```

The proxy itself is not exposed as an Onyx-app FastAPI route — it speaks HTTP-proxy protocol on its own port. Admin observability of the proxy goes through `/api/admin/craft/egress/health` (proxied to the egress service via the api_server) which returns `{ ok, ca_fingerprint, in_flight_requests, last_error }`.

## Relevant Files / Onyx Subsystems

**New: egress proxy module:**
- `backend/onyx/craft/egress_proxy/__init__.py` — module shell.
- `backend/onyx/craft/egress_proxy/__main__.py` — `python -m onyx.craft.egress_proxy` entrypoint; builds the mitmproxy `Master`, registers addons, runs the loop.
- `backend/onyx/craft/egress_proxy/config.py` — `EgressProxyConfig` dataclass (port, DB DSN, CA path, mitmproxy options); reads from env.
- `backend/onyx/craft/egress_proxy/ca.py` — load-or-generate CA, decrypt private key on startup, leaf-cert generation cache.
- `backend/onyx/craft/egress_proxy/auth.py` — `Proxy-Authorization` validator → resolves session token to `(BuildSession, User, Tenant)`. Uses the same cache strategy as `require_sandbox_session_token` from project #1.
- `backend/onyx/craft/egress_proxy/addons/resolver.py` — host → service lookup (with positive + negative caching).
- `backend/onyx/craft/egress_proxy/addons/classifier.py` — apply `classification_rules`, return category.
- `backend/onyx/craft/egress_proxy/addons/approver.py` — gate the request; talk to `craft_approvals` (project #6) over a small in-process API.
- `backend/onyx/craft/egress_proxy/addons/injector.py` — decrypt `CraftSecret`, render `auth_template`, set headers.
- `backend/onyx/craft/egress_proxy/addons/audit.py` — emit lifecycle events to the audit outbox (project #9).
- `backend/onyx/craft/egress_proxy/outbound.py` — forward to upstream via `httpx.AsyncClient`; tear down/replay paths.

**New: DB models + alembic migration:**
- `backend/onyx/db/models.py` — five new tables described above.
- `backend/onyx/db/enums.py` — `CraftAuthScheme`, `CraftGrantScope`, `CraftEgressCategory`.
- `backend/alembic/versions/<rev>_craft_egress_interception.py` — schema migration.
- `backend/onyx/db/craft_intercepted_service.py` — CRUD helpers (mirrors `oauth_config.py`).
- `backend/onyx/db/craft_egress_secret.py` — secret create / rotate / delete with explicit decrypt-only-where-needed pattern.

**New: admin & sandbox routes:**
- `backend/onyx/server/features/build/api/admin_intercepted_services.py` — admin CRUD endpoints described above.
- `backend/onyx/server/features/build/api/sandbox_egress.py` — `/ca.pem` and `/services` (session-token auth).
- `backend/onyx/server/features/build/api/admin_egress_health.py` — proxies a healthcheck to the egress service.

**Existing files to touch:**
- `backend/onyx/server/features/build/sandbox/base.py` — `setup_session_workspace` writes the proxy env vars and CA cert. Each backend implements its own version of "materialize CA" (image-baked for K8s, env-injected for docker, none for local).
- `backend/onyx/server/features/build/sandbox/local/local_sandbox_manager.py` — explicit no-op for proxy wiring; document that `local` is dev-only.
- `backend/onyx/server/features/build/sandbox/docker/docker_sandbox_manager.py` (when project #2 lands) — sandbox containers join `onyx_craft_sandbox` network; proxy is also on that network.
- `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py` — sandbox pod gets a NetworkPolicy egress-allowlisted to the egress-proxy service; CA cert mounted via ConfigMap or baked into image.
- `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile` — install Onyx CA into `/etc/ssl/certs/`. CA fingerprint baked at image build, replaceable via the `/ca.pem` endpoint at session setup if the deployment has rotated.
- `backend/onyx/server/features/build/sandbox/util/opencode_config.py` — no change today; future skill-level "this skill needs service X" hint is left for project #3.
- `backend/onyx/server/features/build/AGENTS.template.md` — agent guidance: "to call external services, just use their normal URLs; Onyx will inject credentials and prompt the user for approval where needed."

**Deployment / packaging:**
- `deployment/docker_compose/docker-compose.yml` — new `onyx-craft-egress` service:
  - image: `onyxdotapp/onyx-backend:<tag>` (same image; different command),
  - command: `python -m onyx.craft.egress_proxy`,
  - depends_on: `relational_db`, `redis`,
  - on the `onyx_craft_sandbox` network,
  - `ENCRYPTION_KEY_SECRET` and `POSTGRES_*` env vars passed in.
  No new image; the egress proxy runs from the existing backend image.
- `deployment/helm/charts/onyx/templates/craft-egress-deployment.yaml` — k8s deployment + service for the proxy.
- `deployment/helm/charts/onyx/templates/craft-sandbox-networkpolicy.yaml` — namespaced NetworkPolicy restricting sandbox egress to the proxy.
- `backend/requirements/default.txt` — add `mitmproxy>=10,<11` (heavy-ish — pulls cryptography, h2, kaitaistruct; ~30MB image growth). Pin tightly.

**Seed data:**
- `backend/onyx/craft/egress_proxy/builtin_services.py` — initial `CraftInterceptedService` rows for Linear, HubSpot, GitHub, Slack, Google Calendar, generic OpenAI/Anthropic-compatible endpoints. Seeded via a one-time alembic data migration; admins can edit, disable, or delete after seed.

## Tests

Lightweight, focused on the boundary properties the proxy promises. The mitmproxy library has its own deep test suite — we don't re-test TLS, CONNECT, or HTTP/2 framing.

**Unit (small, no daemon):**
- `backend/tests/unit/onyx/craft/egress_proxy/test_classifier.py` — feed synthetic `(method, path, body)` tuples through the classifier with a fixture `CraftInterceptedService` set; assert the right category. Cover the GraphQL operation-name path (`POST /graphql` with `body_match` rule).
- `backend/tests/unit/onyx/craft/egress_proxy/test_resolver.py` — host-prefix matching: most-specific wins, exact > wildcard, no-match → pass-through marker.
- `backend/tests/unit/onyx/craft/egress_proxy/test_auth_template.py` — render auth templates: `Bearer {{secret}}`, `Basic {{secret}}`, custom-header form, HMAC. Confirms secret values never appear in any audit/log output (use `caplog` to assert absence).
- `backend/tests/unit/onyx/craft/egress_proxy/test_ca.py` — generate-on-first-boot, encrypt with the test fernet key, decrypt at startup, leaf-cert cache eviction.

**External dependency unit (one file, the load-bearing one):**
`backend/tests/external_dependency_unit/craft/egress_proxy/test_egress_e2e.py`
- Spins up the proxy as a subprocess against the live test DB, with a dummy `CraftInterceptedService` for `httpbin.org` and a `CraftSecret` "supersecret".
- A test client points its `HTTPS_PROXY` at the proxy and trusts the freshly-generated test CA.
- Assertions:
  - `GET /headers` → response includes `"Authorization": "Bearer supersecret"` (proxy injected); the test client never set it.
  - `POST /post` → classified as WRITE; with default `approve_always`, an approval row is created and the request hangs; auto-approving via direct DB write resumes the flow with the same body.
  - `DELETE /delete` → classified as DESTRUCTIVE; with `deny`, returns `403`.
  - Without a `Proxy-Authorization` token, returns `407`.
  - With an invalid/expired token, returns `407`.
  - `GET https://example.com/` (no service registered) → pass-through with no Authorization header injected; emit a `passthrough` audit event.
- Skipped on CI runners without an outbound network; mark with the existing skip pattern.

**Integration (one file):**
`backend/tests/integration/tests/build/test_sandbox_egress.py`
- Uses the standard Craft session integration fixtures.
- Boots a real sandbox session, runs a skill that does `curl https://api.test-fixture.local/...` (test fixture host registered as a `CraftInterceptedService`).
- Asserts the request reached the test fixture upstream with the injected header, and that the audit outbox has the expected event sequence.
- Negative path: register a service with `approve_always` for WRITE; have the skill POST; assert the session is left in `WAITING_FOR_APPROVAL` and the request didn't reach the upstream until the test approves it.
- We do **not** matrix this across all three sandbox backends — running it against `docker` is enough.

**Playwright:** none in this project. Admin UI for managing intercepted services is part of project #8 (`admin-ui.md`), and gets its own E2E tests there.

**Manual smoke (do this before merging):**
- `docker compose up` with `SANDBOX_BACKEND=docker` and `ENABLE_CRAFT=true`. Confirm the `onyx-craft-egress` container is up. Open a Craft session, run an OpenCode skill that does `curl -v https://httpbin.org/headers`. Confirm:
  - The `curl` succeeds (TLS handshake against the Onyx CA).
  - `httpbin` echoes back an `Authorization` header that the agent never sees.
  - The egress audit log shows `received → classified READ → injected → forwarded → responded`.
- Approval path: configure a service with `approve_always` for WRITE. Have the agent POST. Confirm the session UI shows a pending approval; approve it; confirm the upstream POST goes through with the snapshot's body and `Idempotency-Key`.
- Pass-through path: agent fetches a public URL with no service registered. Confirm it works, no auth injected, audit shows `passthrough`.
- Direct-egress block: from the sandbox container, attempt `curl --noproxy '*' https://api.linear.app`. Confirm the connection is refused (NetworkPolicy / bridge network blocks it).
- CA rotation: rotate the CA in the admin UI, restart the proxy, confirm the next session picks up the new CA cert via `/api/build/sandbox/egress/ca.pem` and the previous session's existing connections fail-and-retry cleanly.

That's enough for V1. Heavier coverage — fuzzing the proxy with malformed CONNECT, HTTP/2 stream-level abuse, large-body replay edge cases, multi-replica DB read consistency — waits until we've seen real traffic patterns from production.
