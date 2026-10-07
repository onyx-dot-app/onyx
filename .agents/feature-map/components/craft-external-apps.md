# Craft External Apps and Egress Proxy

> The security core of Craft. Every outbound HTTPS call a Craft sandbox makes
> is relayed through `sandbox-proxy`, a `mitmproxy`-based man-in-the-middle
> that terminates TLS with its own CA and identifies the sandbox and user.
> It matches each call against connected external apps and MCP servers. For
> a matched call it enforces an admin policy (`ALWAYS`/`ASK`/`DENY`) and
> injects the real credential in place of a sandbox-visible placeholder. It
> resolves the session only for `ASK` actions. It forwards unmatched traffic
> upstream unchanged, under the sandbox egress rules.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** craft
**Edition:** CE, with a Cloud-only lockdown on built-in credential editing (see `[[craft-admin]]`)
**Owns:**
`backend/onyx/sandbox_proxy/` (`server.py`, `backend.py`, `request_evaluator.py`,
`credential_injection.py`, `approval_cache.py`, `identity.py`, `identity_k8s.py`,
`identity_docker.py`, `ca.py`, `ca_k8s.py`, `ca_docker.py`, `errors.py`,
`logging_utils.py`, `mcp_jsonrpc.py`, `addons/gate.py`, `resolvers/external_app.py`,
`resolvers/mcp_server.py`, `resolvers/mcp_matching.py`, `resolvers/onyx_pat.py`),
`backend/onyx/external_apps/` (`credentials.py`, `token_refresh.py`,
`matching/engine.py`, `matching/rules.py`, `matching/request.py`, `providers/`),
`backend/onyx/db/external_app.py`, `backend/onyx/db/gated_app.py`,
`backend/onyx/server/features/build/external_apps/` (`api.py`, `models.py`,
`oauth.py`), `backend/onyx/server/features/build/approvals/api.py`,
`backend/onyx/server/features/build/db/action_approval.py`

**Read first:** `[[craft-admin]]` for the admin surface that configures what
this document enforces, then
`docs/craft/features/egress-proxy-and-approvals/README.md` for the design
rationale, and `docs/craft/features/external-apps/action-policies.md` and
`oauth-token-refresh.md` for the policy and refresh contracts.

---

## 1. What the user experiences

A Craft agent can call out to the public internet freely (installing
packages, fetching docs) and, once the user has connected an app (Slack,
Gmail, Linear, GitHub, a custom API, an MCP server), it can act as that user
against that service: read a Slack channel, create a Linear issue, send a
Gmail draft.

If the admin has set an action to require approval, the agent's attempt
pauses. A card appears in the session ("Craft is requesting approval to
create a Linear issue") and the user approves, rejects, or (for some
approvals) grants the same action for the rest of the session. If the admin
has set an action to always deny, the call fails immediately with a message
telling the agent the integration is blocked by policy, not a silent no-op.

The agent never sees the actual Slack token, Gmail OAuth token, or Onyx API
key it is using. It is issued placeholders; the real secret is substituted in
transit.

---

## 2. Surfaces

### Proxy process

`sandbox-proxy` runs `python -m onyx.sandbox_proxy.server`
(`backend/onyx/sandbox_proxy/server.py:main`). It is not an HTTP API in the
usual sense; every Craft sandbox's `HTTP_PROXY`/`HTTPS_PROXY` points at it, so
its "surface" is every outbound request a sandbox makes. It also exposes
`GET /healthz` on `SANDBOX_PROXY_HEALTHZ_PORT`
(`server.py:_build_healthz_handler`), gated on CA readiness and identity-lookup
sync (`server.py:_Readiness`).

### User-facing HTTP endpoints (outside the proxy)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/api/build/apps/{id}/oauth/start` | `start_external_app_oauth` (`server/features/build/external_apps/oauth.py`) | Begins a user's per-user OAuth connect flow for a built-in app. |
| POST | `/api/build/apps/oauth/callback` | `handle_external_app_oauth_callback` (`oauth.py`) | Exchanges the authorization code, stamps `expires_at`, stores per-user credentials. |
| GET | `/api/build/approvals/sessions/{session_id}/live` | `list_live_approvals` (`server/features/build/approvals/api.py`) | Polled by the frontend to render pending approval cards. |
| POST | `/api/build/approvals/{approval_id}/decision` | `submit_decision` (`approvals/api.py`) | User approves or rejects a parked request. |
| POST | `/api/build/approvals/{approval_id}/session-grant` | `submit_session_grant` (`approvals/api.py`) | Approves and remembers the grant for the rest of the session (see §4.5). |

Admin CRUD for `ExternalApp` (`/api/build/admin/apps*`) is owned by
`[[craft-admin]]`; this document owns what those settings mean at request
time.

### Environment / configuration

| Variable | Where | Effect |
|---|---|---|
| `SANDBOX_PROXY_LISTEN_PORT`, `SANDBOX_PROXY_HEALTHZ_PORT` | `server/features/build/configs.py` | Proxy listen and health ports. |
| `SANDBOX_PROXY_LISTEN_HOST` | `configs.py` | Proxy and health listener; defaults to `0.0.0.0`. Use `::` for IPv6-only clients. |
| `SANDBOX_PROXY_ALLOW_GLOBAL_CLIENTS` | `configs.py` | Defaults to `false`. Enable for global IPv6 sandbox addresses only with restricted proxy ingress. Known sandbox identity remains required. |
| `SANDBOX_PROXY_INTERNAL_CIDRS` | `configs.py` | Comma-separated internal VPC, pod, Service, node, and connected-network ranges, including global IPv6 ranges. The proxy blocks destinations in these ranges. |
| `SANDBOX_PROXY_SSL_VERIFY_UPSTREAM_TRUSTED_CA` | `configs.py` | mitmproxy upstream cert verification mode. |
| `SANDBOX_BACKEND` (`SandboxBackend.KUBERNETES`/`DOCKER`) | `configs.py` | Selects `K8sSecretCAStore`/`K8sInformerLookup` vs. `FileCAStore`/`DockerEventsLookup` (`sandbox_proxy/backend.py:build_ca_store`, `build_ip_lookup`). |
| `SANDBOX_PROXY_CA_SECRET`, `SANDBOX_PROXY_CA_CONFIGMAP`, `SANDBOX_PROXY_NAMESPACE` | `configs.py` | K8s CA persistence and cross-namespace projection targets (`ca_k8s.py`). |
| `SANDBOX_PROXY_CA_VOLUME_PATH` | `configs.py` | Docker CA persistence volume (`ca_docker.py`). |
| `ONYX_SERVER_URL` | `configs.py` | The one internal host the proxy allows through the destination-block, and the host the `OnyxPatResolver` claims (`gate.py:_parse_api_server`, `resolvers/onyx_pat.py`). |
| `SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS` | `configs.py` | How long the proxy parks a request awaiting an `ASK` decision before claiming `EXPIRED` (`gate.py:_await_decision`). |
| `MCP_SESSION_TAG_HEADER` | `configs.py` | Header opencode's in-process MCP client uses to carry the session tag (`gate.py:_extract_session_tag`). |
| `PARSER_MAX_BODY_BYTES` | `sandbox_proxy/addons/gate.py` (constant, not env) | 32 MiB request-body cap; see §9. |
| `AUTO_PROVISION_DEFAULT_EXTERNAL_APPS` | `backend/onyx/configs/app_configs.py` (default `false`) | Seeds Onyx-managed built-ins (disabled) on tenant creation. |

The proxy requires `SANDBOX_PROXY_INTERNAL_CIDRS` at startup when the listener
uses IPv6 or global clients are enabled. Invalid CIDRs also prevent startup.
Internal destinations remain blocked for HTTP and CONNECT. The exact
`ONYX_SERVER_URL` host and port remain the only internal destination exception.
Kubernetes identity lookup indexes each pod's primary `status.pod_ip`.
Use listeners and Services in that address family: IPv4 remains the default;
IPv6 listeners support IPv6-only deployments. Switching an IPv4-primary
dual-stack deployment to secondary IPv6 pod addresses is not supported.

---

## 3. Data model

```
ExternalApp ----------------------< ExternalAppUserCredential (per user, per app)
    |  organization_credentials (encrypted)     user_credentials (encrypted)
    |  auth_template (header -> "{placeholder}" template)
    |  upstream_url_patterns (glob for CUSTOM, regex for built-in)
    |
    +--< ExternalApp__Skill >--- Skill

GatedApp (kind, target_id) -- one row per external_app OR mcp_server
    |  external_app_id XOR mcp_server_id  (ck_gated_app_single_target)
    +--< GatedActionPolicy (action_id -> ALWAYS|ASK|DENY, sparse)

ActionApproval  -- one row per gated request the proxy parked or auto-decided
    session_id -> BuildSession
    actions: JSONB list[MatchedAction-shaped dict], strictest-first
    decision: NULL (pending) | APPROVED | REJECTED | EXPIRED
    decided_via: USER | PRE_APPROVAL | SESSION_GRANT (NULL = legacy/proxy-claimed)
```

- `ExternalApp` (`backend/onyx/db/models.py:ExternalApp`): the configured
  app. `upstream_url_patterns` is a plain regex list for built-ins and a glob
  list for `CUSTOM` (translated via `ExternalApp.upstream_url_regexes`). `organization_credentials` and (on
  `ExternalAppUserCredential`) `user_credentials` are `EncryptedJson` /
  `SensitiveValue`, read only via `.get_value(apply_mask=False)`.
- `ExternalAppUserCredential` (`models.py`): one row per `(external_app_id,
  user_id)`. `granted_scopes` is `NULL` when the provider didn't report a
  scope grant, a list when it did; the two must not be conflated.
- `GatedApp` (`models.py`): the shared identity row for anything
  policy-gated. `CheckConstraint ck_gated_app_single_target` enforces exactly
  one of `external_app_id` / `mcp_server_id`. Rows are created lazily
  (`onyx/db/gated_app.py:get_or_create_gated_app_id`); a target with no row
  has never been policied or approved.
- `GatedActionPolicy` (`models.py`): sparse per-action override, one row
  per `(gated_app_id, action_id)`. An unset action resolves to the catalog's
  `default_policy` at read time
  (`external_apps/providers/registry.py:effective_policy`), not a stored row
  with a default value.
- `ActionApproval` (`models.py`): one row per gated request, whether
  parked for a human or auto-decided by a grant. `decision IS NULL` means
  pending or a proxy-crash orphan; `actions[0]` (JSONB, insertion-sorted
  strictest-first) is what governed the request
  (`server/features/build/db/action_approval.py:insert_action_approval`).
- `Sandbox.encrypted_pat` (`models.py`): the sandbox's own scoped Onyx
  API token, decrypted only inside `OnyxPatResolver.resolve`
  (`sandbox_proxy/resolvers/onyx_pat.py`).
- `BuildSession` (`models.py`): the session an `ASK` request is
  attributed to; see `[[craft-sessions]]`.

---

## 4. How it works

### 4.1 The life of one outbound request

```
sandbox process (opencode / a tool call)
  │  HTTP_PROXY / HTTPS_PROXY points at sandbox-proxy
  ▼
1. TLS termination (MITM)
     mitmproxy decrypts the CONNECT tunnel using the proxy's own CA
     (ca.py, ca_k8s.py / ca_docker.py), which the sandbox was made to trust
     at boot (firewall-init.sh). GateAddon.http_connect also captures the
     in-band session tag off Proxy-Authorization here: it is only visible
     on the CONNECT, not the decrypted inner request.
     sandbox_proxy/addons/gate.py:GateAddon.http_connect
  │
2. Destination checks and address pinning
     is_destination_blocked(config, host, port) rejects non-global addresses
     and configured internal CIDRs, except ONYX_SERVER_URL's exact host:port.
     http_connect and request check destinations before processing traffic.
     server_connect resolves and validates all answers again, then pins the
     upstream TCP connection to those addresses through UpstreamEventLoop.
     No new hostname lookup occurs between validation and connection.
     The original hostname remains in server.address and TLS SNI, preserving
     hostname verification, MITM processing, and credential injection.
     sandbox_proxy/destination_policy.py:resolve_destination, pin_destination,
     UpstreamEventLoop; sandbox_proxy/addons/gate.py:GateAddon.server_connect
  │
3. Identity resolution
     GateAddon._resolve_and_match extracts the client's source IP and calls
     IdentityResolver.resolve_sandbox(src_ip): backend-specific IP->identity
     lookup (K8sInformerLookup watches sandbox pods; DockerEventsLookup
     streams container events), then a DB read of Sandbox.user_id. Unknown IP
     -> 403 unidentified_sandbox (fail closed).
     sandbox_proxy/identity.py:IdentityResolver.resolve_sandbox
  │
4. Body-size gate
     flow.request.raw_content is None (streamed body) or > 32 MiB
     (PARSER_MAX_BODY_BYTES) -> 403 body_too_large before the matcher ever
     parses it.
     sandbox_proxy/addons/gate.py:PARSER_MAX_BODY_BYTES
  │
5. App / MCP matching
     CompositeRequestEvaluator tries ExternalAppRequestEvaluator then
     McpRequestEvaluator, first non-None verdict wins. The external-app
     evaluator matches request.url against every enabled app's
     upstream_url_patterns (resolve_app_for_url), then classifies the request
     into catalog action(s) via recognize_actions + apply_credential_gate.
     The MCP evaluator attributes by host + longest-path-prefix
     (resolvers/mcp_matching.py:match_request) among the user's accessible
     craft-enabled MCP servers, then parses the JSON-RPC body
     (mcp_jsonrpc.py:classify_mcp_request) to find the invoked tool name(s).
     A matcher exception, or no app/server owning the URL at all, yields
     matched_actions = None ("off-catalog").
     sandbox_proxy/request_evaluator.py:CompositeRequestEvaluator.evaluate
  │
6. Policy evaluation
     matched_actions is None        -> off-catalog: skip policy evaluation (ungated),
                                        but continue to step 7 for host-based credential
                                        injection or a credential-error block.
     governing_action.policy DENY   -> 403 policy_denied, no DB row, request not forwarded.
     governing_action.policy ALWAYS -> proceed straight to credential injection (step 7).
     governing_action.policy ASK    -> resolve the originating BuildSession from the
                                        in-band session tag (fail closed if absent/
                                        unverifiable); check for a reusable grant
                                        (scheduled-task pre-approval, or a live
                                        session grant); if none, persist an
                                        ActionApproval row, announce it, and park
                                        on a wake channel until decided or expired.
     sandbox_proxy/addons/gate.py:GateAddon._resolve_and_match, ._await_decision
  │
7. Credential injection
     CredentialInjectionDispatcher walks OnyxPatResolver, MCPServerResolver,
     ExternalAppResolver in order (first host-claim wins). The claiming
     resolver renders real auth headers (refreshing an expiring OAuth token
     first, if needed) and the dispatcher writes them onto flow.request.
     A claim with no headers still counts as CLAIMED (forward as-is); a
     resolver that cannot produce a credential raises
     CredentialUnavailableError -> 403 credential_error.
     sandbox_proxy/credential_injection.py:CredentialInjectionDispatcher.apply
  │
8. Upstream call
     mitmproxy forwards the (possibly header-rewritten) request to the real
     host. The Proxy-Authorization and MCP session-tag headers are stripped
     first so they never reach the origin.
     sandbox_proxy/addons/gate.py:GateAddon.request
```

### 4.2 The CA: what it is, what it can and cannot see

The proxy generates a self-signed CA (RSA-4096, 5-year validity,
`x509.BasicConstraints(ca=True, path_length=0)`,
`sandbox_proxy/ca.py:CABootstrap._generate_ca`) once per deployment and
persists it: a Kubernetes `Secret` in the proxy's own namespace holding
`ca.crt`/`ca.key`, with only the public cert mirrored into a `ConfigMap` in
the sandbox namespace for cross-namespace mounting
(`sandbox_proxy/ca_k8s.py:K8sSecretCAStore`); or a shared Docker Compose
volume where `ca.key` is `0600` root-owned and `ca.crt` is world-readable
(`sandbox_proxy/ca_docker.py:FileCAStore`). Multiple proxy replicas cold-start
safely by racing on `Secret`/file creation; the loser reloads the winner's CA
(`CAStoreConflictError`).

The sandbox trusts this CA at boot
(`docs/craft/features/egress-proxy-and-approvals/README.md`: `firewall-init.sh`
installs it into the OS trust store and several SDK-specific CA env vars:
`NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`,
`AWS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `GIT_SSL_CAINFO`). This is what lets
mitmproxy MITM every HTTPS connection the sandbox makes: it terminates the
sandbox's TLS with a certificate it mints on the fly, signed by this CA, and
opens its own separate TLS connection to the real upstream.

**What this means (unsoftened):** the proxy sees every HTTPS request and
response body in plaintext from every Craft sandbox in the deployment, for
any host the sandbox talks to, not only connected apps. This is a private CA
scoped only to intercepting a sandbox's own outbound traffic; it is not
usable to impersonate a public site to anyone outside that sandbox's proxy
path, and the private key never leaves the CA store described above. I could
not verify, from this code, whether the plaintext bodies the proxy decrypts
are logged, persisted, or forwarded anywhere beyond the immediate
request/response cycle; `logging_utils.py` logs only metadata (host, method,
app name, action type, policy, credential outcome), never bodies or header
values, but that does not rule out other observability paths outside this
component's code.

### 4.3 Identity: is it spoofable from inside the sandbox

Base identity (`sandbox_id`, `user_id`, `tenant_id`) is resolved purely from
the TCP source IP of the connection into the proxy
(`sandbox_proxy/identity.py:IdentityResolver.resolve_sandbox`), against a
cache the proxy itself builds by watching sandbox pods/containers
(`identity_k8s.py:K8sInformerLookup`, `identity_docker.py:DockerEventsLookup`).
Code inside the sandbox cannot change its own source IP as seen by the proxy,
so this layer is not spoofable from inside a sandbox in either backend.

**This assumes the deployment topology puts one sandbox per pod/container
with a stable, uniquely-labelled IP, and that nothing NATs multiple
sandboxes behind one IP the proxy sees.** Both lookups fail loud on a
duplicate IP mapping to two different `sandbox_id`s at initial sync
(`identity_k8s.py:_initial_list`, `identity_docker.py:_initial_sync`),
which is the code's own acknowledgment of that assumption.

Session-level identity (which `BuildSession` an `ASK` request belongs to) is
different: it rides an in-band tag (the `BuildSession` id, sent as the
`Proxy-Authorization` basic-auth username by an opencode plugin,
`session-proxy-tag.ts`) or, for opencode's in-process MCP client, a separate
header (`MCP_SESSION_TAG_HEADER`). Both are **forgeable by code running
inside the sandbox** (`gate.py:_extract_session_tag`'s own comment says so
explicitly). The proxy bounds the damage, not eliminates it:
`resolve_session_by_id` verifies the tagged session belongs to the
IP-resolved `user_id`
(`identity.py:IdentityResolver.resolve_session_by_id`), so a forged tag can
only misattribute an approval to a **different session of the same user**,
never to another user or tenant. A tag that doesn't resolve at all fails
closed (`session_missing`/`session_malformed`/`session_unverified` ->
`no_active_session`, no guessed fallback).

### 4.4 Credential injection: placeholder in, real secret out

Sandboxes are issued placeholders, never real secrets
(`ONYX_PAT=replaced_by_egress_proxy`, an opencode LLM `api_key` placeholder,
`GH_TOKEN=replaced_by_egress_proxy`, per
`docs/craft/features/egress-proxy-and-approvals/README.md`). The three
resolvers registered in `sandbox_proxy/server.py:build_resolvers` each claim
requests by host, not by the placeholder value:

- `OnyxPatResolver` (`resolvers/onyx_pat.py`): claims requests to the
  `ONYX_SERVER_URL` host+port, decrypts `Sandbox.encrypted_pat`, and injects
  it as both `API_KEY_HEADER_NAME` and its alternative name. See
  `[[auth-and-identity]]` for what a sandbox PAT is scoped to do.
- `MCPServerResolver` (`resolvers/mcp_server.py`): claims a craft-enabled MCP
  server's host (+ path prefix), resolves the sandbox owner's stored MCP
  credentials, refreshing an expired OAuth token first if needed
  (`refresh_mcp_oauth_token_if_expired`).
- `ExternalAppResolver` (`resolvers/external_app.py`): claims a request the
  matcher has already attributed to a connected `ExternalApp`, refreshes an
  expiring OAuth token (`ensure_fresh_credentials`), then renders the app's
  `auth_template` against the merged org + per-user credentials
  (`external_apps/credentials.py:resolve_injection_headers`).

**Verified:** the agent's process never receives the rendered header value.
`build_auth_headers` (`external_apps/credentials.py`) substitutes
`{placeholder}` fields via `str.format`, which "does not re-interpret braces
inside the substituted values" (the function's own docstring) and the
result is written directly onto the outbound `flow.request.headers`
(`credential_injection.py:CredentialInjectionDispatcher.apply`) inside the
proxy process, never echoed back to the sandbox in any response body or
header the code constructs.

**What happens if the agent tries to read the credential directly:** I could
not find a code path that would let it. The sandbox process only ever holds
the placeholder string; the real value exists only inside the proxy
process's memory and the encrypted DB columns
(`ExternalApp.organization_credentials`, `ExternalAppUserCredential.user_credentials`,
`Sandbox.encrypted_pat`, all `EncryptedJson`/`SensitiveValue`). A sandbox
attempting to curl the credential-issuing DB or the proxy's own control
plane directly, rather than through a matched app request, would be a
request to an internal address and blocked by `is_destination_blocked`
(§4.1 step 2) before it ever reached anything that could answer.

### 4.5 Approvals

For an `ASK`-policied action with no applicable grant,
`GateAddon._persist_approval_row` inserts a pending `ActionApproval` row,
adds it to an in-memory `ParkedApprovals` set, and best-effort `RPUSH`es its
id onto `approval:announce:{session_id}` (`approval_cache.py:announce_approval`)
so the chat-stream merger can surface the card on the live SSE stream; a miss
just falls back to the frontend's next `/live` poll
(`GET /api/build/approvals/sessions/{session_id}/live`). The proxy then
`BLPOP`s `approval:wake:{approval_id}` for up to
`SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS`
(`approval_cache.py:wait_for_wake`); the user's decision
(`POST /api/build/approvals/{approval_id}/decision`) writes the DB row via
`try_record_decision` (the sole race arbiter,
`server/features/build/db/action_approval.py:try_record_decision`) and
`RPUSH`es the wake key. A timeout with no wake claims `EXPIRED`
conditionally, falling back to whatever decision actually won the DB race
(`gate.py:_claim_expired_or_read_winner`). See `[[craft-sessions]]` for how
the session and its live stream are structured; see
`[[observability]]` for notification delivery
(`_notify_approval_requested`).

Two grant sources let an `ASK` request bypass the human prompt entirely:

- **Scheduled-task pre-approval** (`_scheduled_task_grant`): a `RUNNING`
  scheduled run whose task configuration pre-approved this `(kind, target_id)`.
- **Session grant** (`_session_grant`): the user previously chose
  "approve for this session" via `submit_session_grant`; cached per-action in
  Redis (`approval_cache.cached_session_grants_cover`) with the persisted
  `ActionApproval` rows as the durable source of truth.

Either grant source still writes an `ActionApproval` row (pre-decided
`APPROVED`, tagged with the originating `decided_via`), so the audit trail is
identical in shape whether a human or a grant decided.

### 4.6 OAuth connect and token refresh

Connect: `GET /api/build/apps/{id}/oauth/start` builds the provider's
authorize URL (`server/features/build/external_apps/oauth.py`); the callback
exchanges the code, stamps an absolute `expires_at`
(`external_apps/token_utils.py:stamp_expires_at`) and stores the granted scopes verbatim.

Refresh is lazy and happens at the credential-injection seam, not on a
schedule: `ExternalAppResolver.resolve` calls `ensure_fresh_credentials`
(`external_apps/token_refresh.py`) before rendering headers. It is a fast
no-op when the token isn't stale; when it is, it acquires a
fleet-wide Redis lock (`ea_token_refresh:{tenant}:{app}:{user}`), re-checks
staleness under the lock, POSTs the refresh off any DB connection, and
persists the result. A terminal refresh failure (revoked grant) **clears**
the stored credential rather than raising, so the app reads as disconnected
on the next request rather than the proxy silently forwarding a dead token.
See `docs/craft/features/external-apps/oauth-token-refresh.md` for the full
design rationale (single-flighting, why lazy over background).

### 4.7 Cloud-managed vs. self-hosted credentials

On Onyx Cloud, Onyx owns the OAuth client credentials for the built-in
providers (`OnyxManagedExtApp` subclasses,
`docs/craft/features/external-apps/cloud-managed-app-credentials.md`);
tenants are seeded with these apps disabled at tenant creation
(`AUTO_PROVISION_DEFAULT_EXTERNAL_APPS`). An admin on Cloud can only toggle
enablement and edit action policies for these; credentials, `auth_template`,
and `upstream_url_patterns` are blanked in the admin API response and never
sent to the client. Self-hosted admins configure their own OAuth app
credentials, unchanged. Per-user OAuth (each user's own token) and injection
are identical in both modes; only who owns the *client* credential differs.

### 4.8 MCP through the proxy

MCP traffic is JSON-RPC over HTTP, so every tool invocation looks like
`POST` to the same URL; matching a URL alone cannot distinguish "call tool A"
from "call tool B". `mcp_jsonrpc.py:classify_mcp_request` parses the body (a
single message or a batched array) and classifies it as `PLUMBING`
(handshake, `tools/list`, resource reads, an explicit allowlist plus
`notifications/*`, forwarded ungated with credentials injected),
`TOOL_CALL` (one `MatchedAction` per invoked `tools/call` message, gated at
its per-tool policy, default `ASK`), or `UNCLASSIFIABLE` (anything that
doesn't parse cleanly as one of the above). An `UNCLASSIFIABLE` body on a
matched MCP host produces a single synthetic `DENY` action
(`request_evaluator.py:MCP_UNCLASSIFIABLE_ACTION_TYPE`) so the gate fails
closed instead of forwarding with injected credentials. The credential
resolver (`resolvers/mcp_server.py:MCPServerResolver.resolve`) independently
re-parses the body and refuses to inject onto anything but `PLUMBING` unless
the gate has already produced a verdict for it, so a matcher bug cannot
result in a tool call forwarding with credentials but no policy check.

**Implication for reliability:** MCP gating is coupled to JSON-RPC body
parsing, not just URL routing. A client library that changes framing (batches
differently, adds an unrecognized top-level field, streams the body so
`raw_content` is `None`) can turn a previously-gated tool call into a denied
one, or trip the 32 MiB request-body cap on a legitimately large tool call
payload.
Both evaluator and resolver import the same pure matching primitives
(`resolvers/mcp_matching.py:match_request`, `parse_target`) specifically so
they can never disagree about which server owns a request; see
`[[mcp-and-custom-tools]]` for the MCP server data model and connection UI.

---

## 5. Contracts and invariants

1. **The agent must never be able to read an injected credential.** The
   dispatcher writes rendered headers directly onto the outbound request
   inside the proxy process (`credential_injection.py:apply`); nothing echoes
   a header value back into a response body or log
   (`logging_utils.py` logs header *names*, never values,
   `credential_injected header_names=%s`). I could not verify this against
   every possible upstream response shape (e.g. an API that reflects request
   headers back in its response body is a property of the *upstream*, not
   this proxy, and would leak the header regardless of this contract).
2. **A `DENY` verdict blocks forwarding of the request.**
   The upstream TLS connection may already be open, because mitmproxy's
   default `eager` strategy connects before `request()` sees the decrypted
   request. `_resolve_and_match` sets the 403 and returns before `request()`
   ever reaches credential injection or forwarding
   (`gate.py:GateAddon._resolve_and_match`); no `ActionApproval` row is written for a `DENY`.
3. **Identity is not spoofable for the sandbox/user/tenant triple; it *is*
   spoofable for which session within that user gets attributed.** See §4.3.
   Any change to session-tag handling must preserve the "verified against the
   IP-resolved user" check in `resolve_session_by_id`; removing it would let
   a compromised sandbox process attribute an approval to any session,
   including a different user's if that check is what enforces the boundary.
4. **The CA is scoped to the sandbox and must never leave it.** The private
   key lives only in the CA store (`Secret`/volume) and the proxy process;
   only the public cert is projected to sandboxes. A change that starts
   mounting `ca.key` (or the K8s `Secret` itself) into the sandbox namespace
   breaks this.
5. **An unmatched request's default depends on *what* went unmatched, and
   the two cases differ:**
   - A request that matches **no connected app and no MCP host at all**
     (`resolve_app_for_url` finds nothing, and no MCP server host claims
     it) is **not evaluated by this gate at all**
     (`matched_actions is None` in `request_evaluator.py`). It is governed
     only by the sandbox's own iptables egress lockdown
     (`firewall-init.sh`), which allows general outbound HTTPS. See
     `[[craft-admin]]` §5.4 for why this is intentional, not a leak.
   - A request to a **configured MCP host** whose path is outside every
     `server_url` prefix is not pass-through. `MCPServerResolver.claims`
     still claims the host, and `MCPServerResolver.resolve` blocks the
     request with `CredentialUnavailableError` (`credential_error`).
   - A request that matches a **connected, available app** but no specific
     catalog action defaults to a synthesized whole-domain `ASK`
     (`WHOLE_DOMAIN_ACTION_TYPE = "unspecified"`,
     `matching/engine.py:apply_credential_gate`), not `ALWAYS`. An app whose
     credentials are currently unavailable forwards bare (no prompt) unless a
     matched action is explicitly `DENY`, in which case the `DENY` still
     applies without credentials.
   - An MCP tool call with no admin override defaults to `ASK`
     (`request_evaluator.py:MCP_TOOL_DEFAULT_POLICY`).
6. **MCP matching must fail closed when the body cannot be parsed.** Any
   non-plumbing, non-well-formed-`tools/call` body on a matched MCP host is
   `UNCLASSIFIABLE` and becomes a synthetic `DENY`
   (`request_evaluator.py:_mcp_tool_actions`), never a silent pass-through.
7. **The upstream socket must use only validated destination addresses.**
   `http_connect` and `request` reject forbidden destinations early.
   `server_connect` calls `resolve_destination` and rejects the entire answer
   set if any address is forbidden. `pin_destination` and `UpstreamEventLoop`
   use those approved addresses for the TCP connection without another DNS
   lookup. Preserve the original hostname for TLS SNI, certificate verification,
   and credential matching. Keep the real TLS tests when changing mitmproxy;
   they verify address pinning, hostname checks, and credential injection.
8. **`try_record_decision` is the only writer of a terminal decision;** any
   new path that can end an approval (a new UI action, a new grant source)
   must go through it, not write `ActionApproval.decision` directly, or the
   proxy's wake/expire race arbiter breaks.
9. **External-app matcher exceptions are fail-open to "off-catalog", by
   design; credential resolution and destination blocking are the actual
   security boundary, not the matcher.** A bug in `recognize_actions` must
   not become a way to reach an internal address or bypass the CA/identity
   layers; it only affects whether a request looks like an app action versus
   general internet traffic. MCP is different. After `McpRequestEvaluator`
   attributes a request to a server, an exception from
   `classify_mcp_request` becomes a synthetic `DENY` (fail closed).

---

## 6. Relationships

**Depends on**
- `[[craft-admin]]`: owns `ExternalApp`/`GatedApp` admin CRUD, the
  catalog `default_policy` and `GatedActionPolicy` values this document reads at request
  time, and the network-lockdown-vs-action-gate distinction this document's
  §5 restates precisely for the proxy's own enforcement code.
- `[[craft-sandboxes]]`: the sandbox pod/container this proxy identifies by
  source IP and whose egress it exclusively mediates; `firewall-init.sh` and
  the CA-trust bootstrap live there.
- `[[craft-sessions]]`: `BuildSession` is the unit an `ASK` approval is
  attributed to and the live stream an approval card is announced on.
- `[[auth-and-identity]]`: `Sandbox.encrypted_pat` is a scoped Onyx API
  token whose issuance and permission scope this document does not own;
  `OnyxPatResolver` only injects it.
- `[[mcp-and-custom-tools]]`: `MCPServer` connection config, credentials, and
  the "available in craft" flag this document's MCP resolver and evaluator
  both read.
- `[[access-control]]`: `Permission.FULL_ADMIN_PANEL_ACCESS` gates every
  admin mutation to the tables this document enforces against;
  `Permission.BASIC_ACCESS` gates the user-facing OAuth/approval endpoints.
- `[[multi-tenancy]]`: every DB read/write here opens a tenant-scoped session
  (`get_session_with_tenant`); the Redis cache factory is also tenant-keyed.

**Depended on by**
- Every Craft sandbox session that connects an external app or MCP server,
  or calls back into the Onyx API.
- `[[observability]]`: `create_notification` calls for
  `APPROVAL_REQUESTED` and pre-approved/session-granted actions.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new external app (built-in or custom) | `resolve_app_for_url`'s regex/glob correctness for the new `upstream_url_patterns` (a bad regex is silently skipped, per `[[craft-admin]]`); the app's catalog (`external_apps/providers/`) and default per-action policies; whether the app needs a skill association |
| changes URL/MCP matching (`resolve_app_for_url`, `mcp_matching.py:match_request`, `recognize_actions`) | both `ExternalAppRequestEvaluator` and any credential resolver that independently re-derives attribution (`MCPServerResolver.resolve` re-parses instead of trusting the gate's cache, deliberately); the ambiguous-match fail-closed paths (`AmbiguousMCPTargetError`) |
| changes the default for unmatched requests (whole-domain `ASK`, MCP default `ASK`, or the off-catalog pass-through) | §5 item 5 of this document; `[[craft-admin]]`'s "general internet egress is not admin-approved" invariant; every existing connected app's behavior for actions outside its catalog |
| changes identity resolution (`identity.py`, `identity_k8s.py`, `identity_docker.py`) | the duplicate-IP fail-loud check at initial sync; `/healthz` readiness semantics; the session-tag verification in `resolve_session_by_id` (§4.3); both `SandboxIPLookup` backends must stay behavior-identical |
| changes credential injection (`credential_injection.py`, any resolver) | the first-claim-wins resolver order in `server.py:build_resolvers`; whether a claim with no headers (`CLAIMED`) vs. a hard failure (`BLOCKED`) is still correct for the new resolver; `logging_utils.py`'s "header names only, never values" invariant |
| changes the CA bootstrap or persistence (`ca.py`, `ca_k8s.py`, `ca_docker.py`) | every running sandbox's trust store (a rotated CA without a coordinated sandbox restart breaks every in-flight TLS interception); the K8s cross-namespace `ConfigMap` projection; the half-written-state fail-loud recovery path |
| changes the approval flow (`gate.py`'s park/wake, `approval_cache.py`, `action_approval.py`) | `[[craft-sessions]]`'s live-stream announce path; the SIGTERM drain (`GateAddon.drain_inflight`) that must terminalize every parked approval before the proxy pod exits; the frontend's `/live` polling fallback |
| changes the request body cap (`PARSER_MAX_BODY_BYTES`) | §9's body-limit footgun; whether the new limit still matches or exceeds the relevant upstream's own limit, so the proxy is never the more restrictive failure |
| changes `GatedApp`/`GatedActionPolicy` | both consumers: `external_apps/api.py` (admin writes) and this document's live enforcement (`request_evaluator.py`, `addons/gate.py`); MCP servers share this table with external apps |

---

## 8. How to verify a change

### Tests

```bash
# Proxy unit tests (mock DB/cache/mitmproxy internals)
cd backend && uv run pytest tests/unit/sandbox_proxy

# External dependency unit tests (real Postgres/Redis, direct function calls)
cd backend && uv run pytest tests/external_dependency_unit/sandbox_proxy

# External-app matching engine and policy resolution
cd backend && uv run pytest tests/unit/external_apps/matching/test_engine.py

# Admin + policy + credential integration tests
cd backend && uv run pytest tests/integration/tests/external_apps/test_external_app_action_policies.py
cd backend && uv run pytest tests/integration/tests/external_apps/test_external_apps.py

# Docker end-to-end: a real sandbox + real proxy container
cd backend && uv run pytest tests/integration/tests/craft/docker_e2e/test_approval_gate_docker.py
cd backend && uv run pytest tests/integration/tests/craft/docker_e2e/test_sandbox_network_posture_docker.py
```

`backend/tests/external_dependency_unit/sandbox_proxy/test_gate_claim_arbiter.py`
is the specific test for `try_record_decision`'s race behavior; do not modify
that arbiter without extending it.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`, and
   the sandbox-proxy container/pod logs (`sandbox_proxy` structured log
   lines: `egress_allow`, `egress_block`, `approval_requested`,
   `approval_decided`).
2. Connect an external app (e.g. Slack) as `admin_user@example.com` /
   `TestPassword123!` at `http://localhost:3000`, then start a Craft session
   and have the agent attempt a Slack action.
3. To confirm a `DENY` actually blocks: on `/admin/craft/apps`, set one
   Slack action to `DENY`, have the agent attempt exactly that action, and
   confirm the proxy log shows `egress_block ... reason=policy_denied` with
   **no** `egress_allow` log line (the upstream connection itself may still
   open), and the agent's tool call
   receives the `policy_denied` 403 body verbatim (not a generic failure).
4. To confirm an `ASK` action pauses correctly: set an action to `ASK`, have
   the agent attempt it, confirm an approval card appears in the session,
   approve it, and confirm the proxy's `approval_decided` log shows
   `decision=APPROVED wake=received`.
5. To confirm the credential is never sandbox-visible: with a connected app,
   have the agent try to `curl` the app's real API directly with a bogus
   header and confirm it gets the *upstream's* auth failure, not a value the
   agent supplied; there is no code path by which the agent's own request
   can carry the injected header value forward into anything it can read.

### What "working" looks like

- A `DENY`-policied action is never forwarded to the upstream host (no `egress_allow`
  log line for it), and the sandbox-visible error is `policy_denied`, not a
  generic timeout or connection error.
- An `ASK` action either surfaces exactly one approval card per distinct
  gated request, or resolves immediately against a valid grant, never both.
- Every `egress_allow`/`egress_block` log line carries `tenant`, `sandbox`,
  `host`, and (when gated) `app_name`/`action_type`/`policy`, sufficient to
  reconstruct the decision without reading request bodies.

---

## 9. Footguns

- **The 32 MiB body cap has already caused a real incident.** A body-size
  limit in the egress proxy once caused Craft turns to die after image reads
  (`PARSER_MAX_BODY_BYTES = 32 * 1024 * 1024`, deliberately set to match
  Anthropic's own Messages API limit so the proxy is never the *more*
  restrictive party for a normal LLM call, per `gate.py`'s own comment). Any
  future change to this cap, or the addition of a new large request flow
  (file uploads, big tool-call payloads), must re-check it against the relevant
  upstream's own limit, not just this proxy's number in isolation.
- **General internet reachability from a sandbox is intentional, not a gap
  this proxy should close.** Only requests attributed to a connected
  app/MCP server are policy-gated; everything else (except requests to a
  configured MCP host, which `MCPServerResolver` still claims) is governed by the
  sandbox's iptables lockdown (all outbound traffic dropped except to the
  proxy, which forwards unmatched public traffic). Do not conflate "the sandbox can reach
  `example.com`" with "policy was bypassed." See `[[craft-admin]]` §5.4 and
  §5 item 5 above.
- **A streamed request body (`raw_content is None`) is treated as oversize,
  not unmeasured.** This is deliberate (`gate.py`'s comment: "treat None as
  oversize so a future stream opt-in can't silently bypass the cap"), so
  enabling request streaming anywhere in the chain will start blocking
  requests that previously worked, with `body_too_large`, not a clearer
  error.
- **External-app matcher exceptions fail *open* to off-catalog, not closed.**
  MCP classification failures on an attributed server fail closed (`DENY`).
  A bug in `recognize_actions` or the URL/glob matching does not deny the request; it
  makes the request look like ordinary (ungated) traffic to a host-claiming
  resolver. This is a deliberate trade-off (the matcher is a heuristic
  classifier, not the security boundary) but it means a matching bug is
  silent from a security-audit standpoint: nothing 403s, the action just
  stops being gated.
- **The MCP session-tag header is a same-user attribution hint, not a
  security boundary** (`gate.py`'s own comment on
  `MCP_SESSION_TAG_HEADER`). A compromised sandbox process can forge it to
  attribute an MCP tool-call approval to any of that same user's sessions,
  never another user's. Do not add "sign this header" as a fix; the value
  is already stored in-sandbox in plaintext, so signing buys nothing.
- **`app_type` is immutable and apps aren't identified by name.** Two
  self-hosted GitLab/Jira instances, or two MCP servers, can share a display
  name; every lookup here keys off `(kind, id)` or `external_app_id`, never
  `app_name`. A change that starts matching or granting by name will
  silently collide across such instances (see `[[craft-admin]]` §9).
- **The CA's blast radius is every sandbox in the deployment, not one
  session.** Rotating it, or a bug that stops the K8s `ConfigMap` (or the
  Docker volume's `ca.crt`) from projecting correctly, breaks TLS for every
  running sandbox simultaneously, not just new ones, since existing
  sandboxes only refresh their trust store at boot.
