# Craft Egress Proxy and Approvals

This document describes the implemented Craft egress proxy and approval
system. It is intended to be the durable reference for the runtime system.

The short version:

- Every Craft sandbox is configured to egress through `sandbox-proxy`.
- The proxy is a `mitmproxy` process with a Python gate addon.
- The proxy identifies the sandbox by source IP, matches outbound HTTP(S)
  requests to external-app actions, injects secrets on the wire, and gates
  `ASK` actions on user approval.
- PostgreSQL is the source of truth for approvals. Redis is only a best-effort
  announce/wake/cache layer.
- Sandboxes receive only placeholder credentials and a trusted proxy CA. Real
  Onyx PATs, LLM provider keys, and external-app tokens are resolved by the
  proxy at request time.

## Key Files

Proxy runtime:

- `backend/onyx/sandbox_proxy/server.py` starts mitmproxy, health checks, CA
  bootstrap, identity lookup, request evaluator, credential resolvers, and the
  gate addon.
- `backend/onyx/sandbox_proxy/addons/gate.py` owns request classification,
  approval parking, grant resolution, credential injection dispatch, internal
  destination blocking, and SIGTERM drain cleanup.
- `backend/onyx/sandbox_proxy/identity.py`,
  `identity_k8s.py`, and `identity_docker.py` resolve source IPs to sandbox,
  tenant, and user identity.
- `backend/onyx/sandbox_proxy/request_evaluator.py` turns mitmproxy requests
  into external-app action matches.
- `backend/onyx/sandbox_proxy/credential_injection.py` and
  `backend/onyx/sandbox_proxy/resolvers/` inject Onyx PATs, LLM provider keys,
  and external-app credentials.
- `backend/onyx/sandbox_proxy/approval_cache.py` defines Redis announce, wake,
  and session-grant cache keys.
- `backend/onyx/sandbox_proxy/ca.py`, `ca_k8s.py`, and `ca_docker.py` manage
  the proxy CA.

Approval persistence and API:

- `backend/onyx/db/models.py` defines `ActionApproval`,
  `ExternalAppPolicy`, and `ScheduledTaskPreApprovedApp`.
- `backend/onyx/db/enums.py` defines `EndpointPolicy`,
  `ApprovalDecision`, and `ApprovalDecidedVia`.
- `backend/onyx/server/features/build/db/action_approval.py` owns approval DB
  operations. `try_record_decision` is the race arbiter.
- `backend/onyx/server/features/build/approvals/api.py` exposes live approval
  listing, approve/reject, and approve-for-session.
- `backend/onyx/db/scheduled_task.py` contains scheduled-task pre-approval
  lookups.

External-app policy and matching:

- `backend/onyx/external_apps/providers/` defines provider specs, OAuth flows,
  URL patterns, auth templates, action catalogs, and payload decoders.
- `backend/onyx/external_apps/matching/engine.py` recognizes actions and
  resolves effective policy.
- `backend/onyx/external_apps/matching/rules.py` implements REST route and
  GraphQL operation matchers.
- `backend/onyx/external_apps/credentials.py` renders injected auth headers.
- `backend/onyx/external_apps/token_refresh.py` lazily refreshes OAuth access
  tokens at injection time.

Sandbox and deployment wiring:

- `backend/onyx/server/features/build/sandbox/image/firewall-init.sh` installs
  the proxy CA and applies in-sandbox egress lockdown.
- `backend/onyx/server/features/build/sandbox/image/opencode-plugins/session-proxy-tag.ts`
  tags proxied requests with the originating `BuildSession` id.
- `deployment/helm/charts/onyx/templates/sandbox-proxy/` deploys the Kubernetes
  proxy.
- `deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml` wires
  Kubernetes sandboxes to the proxy.
- `deployment/helm/charts/onyx/templates/network-policy-sandbox-egress.yaml`
  provides the Kubernetes NetworkPolicy backstop for sandbox pods.
- `deployment/docker_compose/docker-compose.craft.yml` wires the Docker backend
  proxy stack.

Frontend:

- `web/src/app/craft/types/approvals.ts` mirrors the approval API.
- `web/src/app/craft/services/apiServices.ts` calls the approvals endpoints.
- `web/src/app/craft/hooks/useLiveApprovals.ts` polls the live approval list.
- `web/src/app/craft/components/approvals/` renders approval cards and payloads.
- `web/src/app/craft/hooks/useBuildStreaming.ts` reacts to
  `approval_requested` packets by refetching live approvals.

## Runtime Shape

### Proxy Process

`sandbox-proxy` runs `python -m onyx.sandbox_proxy.server`. At startup it:

1. Initializes a small SQLAlchemy pool with app name `sandbox_proxy`.
2. Starts `/healthz` on `SANDBOX_PROXY_HEALTHZ_PORT`.
3. Bootstraps or loads the mitm CA and materializes
   `mitmproxy-ca.pem` into the mitmproxy confdir.
4. Starts the backend-specific sandbox IP lookup:
   `K8sInformerLookup` for Kubernetes, `DockerEventsLookup` for Docker.
5. Refuses to serve traffic until the lookup completes initial sync.
6. Registers credential resolvers in this order:
   `OnyxPatResolver`, `LLMProviderKeyResolver`, `ExternalAppResolver`.
7. Starts mitmproxy in regular proxy mode with `GateAddon`.

Readiness depends on the CA being ready, the identity lookup being synced, and
the process not shutting down. If the Kubernetes watch or Docker events stream
disconnects, readiness flips unhealthy while the lookup reconnects.

### Sandbox Network Posture

Every sandbox is configured with `HTTP_PROXY` and `HTTPS_PROXY` pointing at the
proxy and with the proxy CA in common SDK-specific CA env vars:

- `NODE_EXTRA_CA_CERTS`
- `REQUESTS_CA_BUNDLE`
- `SSL_CERT_FILE`
- `AWS_CA_BUNDLE`
- `CURL_CA_BUNDLE`
- `GIT_SSL_CAINFO`

Sandboxes are also given placeholder credentials:

- `ONYX_PAT=replaced_by_egress_proxy`
- opencode LLM `api_key=replaced_by_egress_proxy`
- `GH_TOKEN=replaced_by_egress_proxy`

The sandbox image contains `firewall-init.sh`. It installs the proxy CA into the
trust store, resolves the proxy host to an IPv4 address, sets `OUTPUT DROP`,
allows loopback, allows established connections, allows only TCP to the proxy
IP and port, rejects other IPv4 egress, and drops all IPv6 egress. It then
self-verifies the iptables rules.

Kubernetes runs `firewall-init.sh` as an init container with `NET_ADMIN`.
Docker runs it as the container entrypoint wrapper, starts as root only long
enough to install the firewall and CA, then uses `setpriv` to drop to UID 1000
and clear the capability bounding set before user code runs.

Kubernetes also has a NetworkPolicy backstop: sandbox pods may egress only to
the proxy and DNS. The proxy itself is ingress-restricted to the sandbox
namespace and has broad egress because it must reach public APIs and Onyx
datastores.

### CA Persistence

The proxy CA is stable across proxy restarts so running or restored sandboxes
continue to trust the proxy.

Kubernetes:

- Source of truth: Secret in `SANDBOX_PROXY_NAMESPACE`, containing `ca.crt` and
  `ca.key`.
- Sandbox projection: ConfigMap in `SANDBOX_NAMESPACE`, containing only
  `ca.crt`.
- Multiple proxy replicas cold-start safely by racing on Secret creation; losers
  reload the winning CA.

Docker:

- Source of truth: shared `sandbox_proxy_ca` volume.
- The proxy mounts the volume read-write at `/var/lib/sandbox-proxy/ca`.
- Sandboxes mount the same volume read-only at `/sandbox-ca`, so Docker
  sandboxes can see both `ca.crt` and `ca.key` in the container filesystem.
- `firewall-init.sh` reads only `/sandbox-ca/ca.crt`. `ca.key` is written
  `0600` and root-owned; the Docker sandbox starts as root only for CA install
  and firewall setup, then `setpriv` drops the agent process to UID 1000. This
  is a root-only permission boundary, not the Kubernetes cert-only projection.
- `ca.crt` is the rendezvous file. Half-written states fail loudly instead of
  regenerating and invalidating already-trusted certs.

## Request Lifecycle

### 1. Source IP Resolves To Sandbox Identity

`GateAddon` extracts the TCP peer IP from mitmproxy and asks
`IdentityResolver.resolve_sandbox`.

The backend-specific lookup maps source IP to:

- `sandbox_id`
- `tenant_id`
- sandbox name
- sandbox IP

`IdentityResolver` then loads the `Sandbox` row in the tenant schema to resolve
the owning `user_id`.

If the source IP is missing, unknown, or the DB lookup fails, the proxy returns:

```json
{"error": "unidentified_sandbox", "message": "..."}
```

This is fail-closed. A pod or container not known as an Onyx sandbox cannot use
the proxy.

### 2. Internal Destinations Are Blocked

The proxy blocks sandbox relay attempts to internal destinations. This is
separate from sandbox iptables: the sandbox sees only "connect to proxy", so the
proxy must enforce the real destination.

`destination_is_blocked(host, port)`:

- Allows the configured Onyx API server host and port.
- Blocks literal IPs that are not globally routable.
- Resolves hostnames and blocks if any answer is not globally routable.
- Blocks on DNS resolution failure.

This catches RFC1918, loopback, link-local, cloud metadata ranges, CGNAT,
reserved ranges, IPv6 ULA/link-local/loopback, and IPv4-mapped IPv6 smuggling.

The check runs in three places:

- `http_connect`, before opening a CONNECT tunnel.
- `request`, for plain HTTP and decrypted HTTPS inner requests.
- `server_connect`, as the final backstop before mitmproxy opens the upstream
  connection.

The normal sandbox-visible error is:

```json
{"error": "destination_blocked", "message": "..."}
```

`server_connect` can only kill the upstream connection because it is too late to
write a structured HTTP body.

### 3. Request Body Is Capped

The matcher reads `flow.request.raw_content`. If the body is streamed
(`raw_content is None`) or larger than `PARSER_MAX_BODY_BYTES`, the request is
blocked with `body_too_large`.

The cap is currently 32 MiB, matching Anthropic's Messages API limit so the
proxy is not stricter than the relevant upstream for normal LLM calls.

### 4. External-App Action Matching Runs

`ExternalAppRequestEvaluator` opens a tenant-scoped DB session and:

1. Loads configured external apps in id order.
2. Finds the first app whose `upstream_url_patterns` match the full request URL.
3. Normalizes the request to method, path without query string, and raw body.
4. Recognizes provider catalog actions with REST route or GraphQL operation
   matchers.
5. Applies the credential gate.
6. Decodes JSON or form payload into a displayable dict.

Important matching behavior:

- Built-in apps store regex URL patterns directly.
- Custom apps store glob URL patterns that are translated to regexes.
- Lowest app id wins when patterns overlap.
- Malformed built-in regexes are skipped instead of crashing matching.
- REST matchers compare method and path templates.
- GraphQL matchers parse body operation type and root fields.
- If multiple actions match, the actions are sorted strictest-policy-first using
  `DENY > ASK > ALWAYS`; `actions[0]` is the governing action.

The credential gate is intentionally part of the match result:

- Available app plus catalog match: return matched actions.
- Available app plus no catalog match: synthesize a whole-domain `ASK` action
  with action type `unspecified`.
- Unavailable app plus matching `DENY`: keep only the `DENY` actions, so admin
  block policy still applies even without credentials.
- Unavailable app without `DENY`: return `None`, so the request forwards bare.

"Available" means the linked skill is enabled and the app has renderable auth
headers, unless the app has an empty auth template, in which case no credential
is required.

### 5. Policy Decides Forward, Park, Or Block

If no action match is returned, the proxy treats the request as off-catalog. It
still runs host-level credential injection; this is how Onyx API PATs and LLM
provider keys are injected for requests that are not external-app actions. If no
resolver claims the request, it passes through untouched.

If an action match is returned:

- `DENY`: return `policy_denied`; no `action_approval` row is inserted.
- `ALWAYS`: inject credentials and forward; no `action_approval` row is
  inserted.
- `ASK`: resolve the originating `BuildSession`; then use approval grants or
  park for user decision.

Matcher exceptions fall through as off-catalog traffic. This is deliberate: a
matcher bug must not prevent host-level credential resolvers from replacing
placeholders with real PATs or LLM provider keys. Security does not rely on the
matcher alone; network lockdown and destination blocking are the hard egress
boundary.

### 6. ASK Requires A Verified Session Tag

Only gated `ASK` traffic needs a session. Non-gated traffic only needs sandbox
identity.

The session id is carried in `Proxy-Authorization` basic-auth username. The
sandbox-side opencode plugin
`backend/onyx/server/features/build/sandbox/image/opencode-plugins/session-proxy-tag.ts`
extracts the session id from the session workspace path and rewrites
`HTTP_PROXY` / `HTTPS_PROXY` to include:

```text
http://{session_id}:x@sandbox-proxy:8080
```

For HTTPS, mitmproxy sees this header on the CONNECT request, not on the
decrypted inner request, so `GateAddon.http_connect` caches it by client
connection id. For plain HTTP, the gate can read it directly from the request.

The tag is not trusted by itself. The proxy parses it as a UUID and calls
`IdentityResolver.resolve_session_by_id(session_id, user_id, tenant_id)`, which
only succeeds if the `BuildSession` exists and belongs to the same user that was
resolved from the sandbox source IP.

There is no "most recent session" fallback. Missing, malformed, foreign, stale,
or DB-error session tags fail closed with `no_active_session`.

Before forwarding any request, the proxy strips `Proxy-Authorization` so the
session tag never reaches the origin.

## Approval State Machine

### Approval Rows

`ActionApproval` is one gated request and its decision:

- `approval_id`: primary key.
- `session_id`: FK to `build_session`, cascade delete.
- `actions`: non-empty JSONB list of matched actions, sorted strictest-first.
- `app_name`: display name at the time of request.
- `payload`: decoded request body for review.
- `external_app_id`: FK to `external_app`, nullable and `ON DELETE SET NULL`.
- `decision`: `APPROVED`, `REJECTED`, `EXPIRED`, or `NULL`.
- `decided_at`: timestamp for terminal decisions.
- `decided_via`: `USER`, `PRE_APPROVAL`, `SESSION_GRANT`, or `NULL`.

Pending is represented by `decision IS NULL`; there is no `PENDING` enum value.

`try_record_decision` is the only race arbiter. It runs:

```sql
UPDATE action_approval
SET decision = ..., decided_at = ..., decided_via = ...
WHERE approval_id = ...
  AND decision IS NULL
RETURNING *
```

If another writer already won, it returns `None`. User approve/reject, proxy
timeout, proxy cancel, proxy SIGTERM drain, scheduled-task grants, and session
grants all converge on this one conditional update or on pre-decided inserts
when no parked request can race.

### Redis Coordination

PostgreSQL is authoritative. Redis provides fast cross-process coordination:

- `approval:announce:{session_id}`: proxy to API server. The proxy pushes an
  `approval_id` after committing a pending row. The chat stream merger pops it
  and emits `approval_requested`. TTL: 60 seconds.
- `approval:wake:{approval_id}`: API server to proxy. The API pushes the
  decision after successfully writing it. The parked proxy wakes and proceeds.
  TTL: 30 seconds.
- `approval:session-grant:{session_id}:{external_app_id}:{action_type}`:
  acceleration cache for approve-for-session grants. The DB rows are still the
  durable source. TTL: 1 hour, sliding on use.

Missed Redis announce: the frontend can still refetch `/live`.

Missed Redis wake: the proxy waits until timeout, then reads the winning
decision from Postgres. If the API decision won, the proxy honors it.

### Pending Approval Flow

For an `ASK` request with no grant:

1. The proxy inserts `action_approval` with `decision=NULL`.
2. It adds the approval id to its in-memory parked set.
3. It pushes `approval:announce:{session_id}`.
4. It creates a best-effort `APPROVAL_REQUESTED` notification.
5. It blocks on `approval:wake:{approval_id}` for
   `SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS` seconds. Default: 180.
6. If woken, it uses the decision.
7. If not woken, it tries to claim `EXPIRED`; if another writer won, it reads
   the winner.
8. It forwards only on `APPROVED`. `REJECTED` returns `user_rejected`;
   `EXPIRED` returns `not_authorized`.

The frontend live list is:

```text
decision IS NULL
AND created_at >= now - SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
```

Older undecided rows are treated as proxy-crash orphans and excluded from
`/live`.

### Approve Once

`POST /api/build/approvals/{approval_id}/decision` accepts only `APPROVED` or
`REJECTED`.

The API:

1. Ensures the approval belongs to the calling user through the parent
   `BuildSession`.
2. Returns `NOT_FOUND` for missing and non-owner rows to avoid existence leaks.
3. If already decided with the same decision, returns the existing view
   idempotently.
4. If already decided with a different decision, returns `CONFLICT`.
5. Otherwise records the decision with `decided_via=USER`.
6. Pushes the wake channel best-effort.

### Reject

Reject follows the same endpoint as approve once, with
`decision=REJECTED`. The proxy returns a structured 403 to the sandbox and does
not forward the original upstream request.

### Approve For Session

`POST /api/build/approvals/{approval_id}/session-grant` approves the current
request and later matching requests for the same session.

The API:

1. Ensures the row belongs to the calling user.
2. Requires the row to be live, pending, and tied to an `external_app_id`.
3. Extracts the current row's `ASK` action types.
4. Records the current row as `APPROVED` with
   `decided_via=SESSION_GRANT`.
5. Wakes the current approval.
6. Reads durable session-grant source rows for the same session and app.
7. Hydrates the Redis session-grant cache.
8. Finds other live pending rows in the same session and same external app.
9. Auto-approves those rows when their `ASK` action types are covered by the
   granted action set.
10. Wakes those rows too.

The gate checks session grants before parking. A later multi-action request is
auto-approved only when every `ASK` action type in the request is covered.
Partial coverage still parks.

### Scheduled Task Pre-Approvals

Scheduled task pre-approvals are another grant source inside the same proxy
approval path. A task can store a set of pre-approved external app ids in
`scheduled_task_pre_approved_app`.

For an `ASK` request, the gate checks grant sources in this order:

1. Running scheduled-task grant.
2. Session grant.

A scheduled-task grant applies only when:

- The `BuildSession` has a `ScheduledTaskRun` row.
- That run is currently `RUNNING`.
- The task has a grant for the matched `external_app_id`.

When it applies, the proxy inserts an `action_approval` row already
`APPROVED` with `decided_via=PRE_APPROVAL`, emits a deduped scheduled-task
notification, injects credentials, and forwards. There is no parked request and
no user decision race, so a pre-decided insert is safe.

Admin `DENY` still wins before grants are consulted. `ALWAYS` also bypasses the
grant system because it forwards without an approval row.

When a scheduled run is no longer `RUNNING` (`SUCCEEDED`, `FAILED`,
`SKIPPED`, or `AWAITING_APPROVAL`), grants no longer apply. Interactive
follow-up turns in that scheduled session park like a normal interactive
session.

Do not confuse this with the scheduled-task executor's handling of ACP
`RequestPermissionRequest`. That path marks the scheduled run
`AWAITING_APPROVAL` and emits a scheduled-task notification. It is separate
from the egress proxy's external-app approval gate.

## Credential Injection

The proxy uses first-claim-wins credential dispatch. Resolvers must keep
`claims()` cheap and put DB/network work in `resolve()`.

### Onyx PAT Resolver

`OnyxPatResolver` claims requests whose host and port match
`SANDBOX_API_SERVER_URL`.

It loads the sandbox row and decrypts `Sandbox.encrypted_pat`, then injects both
Onyx API key header names as bearer tokens. The tenant is embedded in the PAT,
so the proxy does not add a separate tenant header.

If the sandbox row is gone, has no PAT, or decryption fails, the resolver raises
`CredentialUnavailableError`; the dispatcher blocks with `credential_error`.

### LLM Provider Key Resolver

`LLMProviderKeyResolver` claims canonical LLM hosts:

- `api.openai.com`
- `api.anthropic.com`
- `openrouter.ai`

It loads the sandbox owner and the user's accessible Craft LLM providers, then
injects the first provider of the matching type. It sets only the relevant auth
header so provider-specific headers like `anthropic-version` survive.

Custom `api_base` hosts are not claimed by this resolver.

### External App Resolver

`ExternalAppResolver` claims only matcher-attributed requests
(`ctx.matched_actions is not None`). The matcher has already proven URL-to-app
attribution; the resolver does not claim by host alone.

Before rendering headers, it calls `ensure_fresh_credentials` for OAuth apps.
That helper:

- Does a cheap stale-token precheck.
- Single-flights refresh with a Redis lock per tenant/app/user.
- Runs token POSTs without holding DB sessions.
- Clears terminally revoked credentials.
- Keeps existing credentials on transient refresh failure.
- Never raises for normal refresh outcomes.

Then the resolver calls `resolve_injection_headers`, which merges organization
credentials and the user's app credentials and renders the app's
`auth_template`. A template placeholder that cannot be filled causes that
header to be omitted.

Empty rendered headers mean "claimed but no headers." The request still
forwards; the upstream 401 is allowed to surface.

## Frontend And Stream Delivery

The proxy never sends the full approval body over the stream. It commits the DB
row, pushes the announce key, and the stream carries only:

```json
{"type": "approval_requested", "approval_id": "...", "session_id": "..."}
```

`merge_events_with_announces` runs two producer threads:

- one for sandbox events
- one polling `approval:announce:{session_id}` every second

Both feed the existing SSE stream. `useBuildStreaming` handles the packet by
invalidating `SWR_KEYS.buildSessionLiveApprovals(sessionId)`.

`useLiveApprovals` fetches
`GET /api/build/approvals/sessions/{session_id}/live` and also refreshes every
10 seconds to catch removals from expiration, another tab, or another user
session.

`LiveApprovalsRegion` renders live approval rows at the trailing assistant slot
in the chat. `ApprovalCard` offers:

- Approve once
- Approve for session
- Reject
- Expand/collapse details
- Action descriptions
- Decoded display payload

Payload decoding is server-side. `ApprovalView.display_payload` calls
`decode_payload(action_type, payload)`. If no decoder exists, or a decoder
fails, the raw payload is returned. Gmail MIME payloads are decoded into
reviewable fields like recipients, subject, body, and attachment metadata.

## Error Contract

Every sandbox-visible proxy block is a 403 JSON response:

```json
{"error": "<stable_code>", "message": "<agent-facing guidance>"}
```

Stable error codes live in `SandboxProxyError`:

- `unidentified_sandbox`: source IP could not be mapped to a known sandbox.
- `no_active_session`: an `ASK` request could not be tied to a verified
  `BuildSession`.
- `body_too_large`: body is streamed or above the parser cap.
- `user_rejected`: user rejected the approval.
- `not_authorized`: approval expired or otherwise did not complete in time.
- `internal_error`: the gate hit an unexpected error and blocked as a
  precaution.
- `policy_denied`: admin policy is `DENY`.
- `credential_error`: a claimed credential resolver failed.
- `destination_blocked`: target destination is internal or unresolved.

The sandbox AGENTS template instructs agents not to retry rejected, expired, or
policy-denied gated actions blindly.

## Shutdown And Cleanup

mitmproxy would normally forward the original request if an addon exception
escapes. The gate catches exceptions around approval handling and writes
`internal_error` to fail closed.

If an exception occurs after an approval row is committed but before a decision
is recorded, the gate attempts to terminalize the row by claiming `EXPIRED` or
reading the existing winner, then sends a wake.

If the sandbox socket closes while the proxy is parked, `_await_decision`
claims or reads a terminal decision and re-raises cancellation so mitmproxy can
release the flow.

On SIGTERM, the proxy:

1. Flips readiness unhealthy.
2. Stops the identity lookup.
3. Walks its in-memory parked approvals.
4. Claims `EXPIRED` or reads the winning decision for each.
5. Sends wake messages best-effort.
6. Waits for tracked request tasks to finish, bounded by the server drain
   timeout.

Kubernetes and Docker both set enough termination grace for this drain path.

## Invariants To Preserve

- Unknown sandbox source IPs must fail closed.
- Gated requests without a verified session tag must fail closed.
- `Proxy-Authorization` must be stripped before forwarding.
- `try_record_decision` must remain conditional on `decision IS NULL`.
- Redis announce and wake must remain best-effort; correctness cannot depend on
  Redis delivery.
- `ActionApproval.actions` must stay non-empty and strictest-policy-first.
- `DENY` must beat all grant sources.
- Session grants must require coverage for every `ASK` action type in a
  multi-action request.
- Scheduled-task grants must require `ScheduledTaskRun.status == RUNNING`.
- Credential resolver failures after a resolver claims a request must block,
  not forward with placeholders.
- Kubernetes sandbox pods must mount only the proxy CA cert, never the Secret
  containing `ca.key`.
- Docker sandboxes currently mount the shared CA volume read-only; `ca.key`
  must remain `0600` and root-owned, and user code must continue to run after
  the entrypoint drops to UID 1000.
- Sandbox egress must remain proxy-only; bypassing `*_PROXY` must not open
  direct internet or internal network access.

## Current Boundaries And Non-Goals

- This system gates HTTP(S) egress. It does not inspect raw TCP protocols.
- `ALWAYS` and `DENY` decisions are logged by the proxy but do not currently
  create `action_approval` rows. `action_approval` is the durable record for
  `ASK` requests and grant-applied `ASK` requests, not a complete audit log of
  every policy decision.
- Custom apps currently rely on URL glob matching and synthesized whole-domain
  `ASK` when available. There is no custom per-action catalog in the current
  implementation.
- If an app is unavailable because credentials cannot be rendered, non-`DENY`
  requests forward bare instead of prompting. This avoids minting approvals for
  actions the proxy cannot actually authenticate.
- The LLM provider resolver claims only canonical provider hosts, not arbitrary
  custom `api_base` endpoints.

## Extension Points

Adding a built-in external app:

1. Add an `ExternalAppProvider` or `OAuthExternalAppProvider`.
2. Define `ProviderSpec` with URL patterns, auth template, org credential
   fields, setup instructions, and endpoint catalog.
3. Add REST or GraphQL `MatchRule`s for each action.
4. Register payload decoders when the approval payload needs a human-readable
   view.
5. Register the provider in `providers/registry.py`.
6. Add unit tests for catalog defaults, matching, credentials, and payload
   display.

Adding a credential source:

1. Implement `CredentialResolver`.
2. Keep `claims()` cheap and side-effect-free.
3. Raise `CredentialUnavailableError` when the resolver owns the request but
   cannot safely render credentials.
4. Register it in `build_resolvers()`.
5. Add tests for claim ordering and failure behavior.

Adding a new approval grant source:

1. Add a resolver method that returns `_ApprovalGrant | None`.
2. Put it in `_resolve_approval_grant` in the desired priority order.
3. Use `decided_via` to distinguish the decision source.
4. Keep DB work inside the existing threaded grant-check path.
5. Ensure any auto-approved forward remains fail-closed if credential dispatch
   raises.

## Test Coverage Map

Unit tests:

- `backend/tests/unit/sandbox_proxy/test_gate.py` covers fail-open/fail-closed
  behavior, policy decisions, session tags, grants, destination blocking,
  credential dispatch, parking, timeout, drain, and terminalization.
- `backend/tests/unit/sandbox_proxy/test_approval_cache.py` covers wake polling
  and session-grant cache coverage.
- `backend/tests/unit/sandbox_proxy/test_credential_injection.py` covers
  first-claim-wins and resolver failures.
- `backend/tests/unit/sandbox_proxy/test_request_evaluator.py` covers app URL
  resolution behavior.
- `backend/tests/unit/external_apps/matching/` covers recognition and policy
  resolution.

External-dependency unit tests:

- `backend/tests/external_dependency_unit/craft/test_action_approval_db.py`
  covers DB ordering, empty-action rejection, conditional decisions, ownership
  lookup, and live filtering.
- `backend/tests/external_dependency_unit/craft/test_approvals_api.py` covers
  live listing, decision idempotency/conflicts, wake pushes, session grants, and
  multi-action views.
- `backend/tests/external_dependency_unit/craft/test_scheduled_task_pre_approvals.py`
  covers running-run grants, non-running exclusions, grant patch semantics,
  pre-decided inserts, and FK behavior.
- `backend/tests/external_dependency_unit/sandbox_proxy/test_gate_claim_arbiter.py`
  pins `_claim_expired_or_read_winner` against real Postgres rows.

Integration tests:

- `backend/tests/integration/tests/craft/k8s/test_approval_gate.py` exercises
  real Kubernetes proxy flows, approve/reject/expire, SIGTERM drain,
  non-gated traffic, missing session tags, unavailable app behavior, SSE
  announce packets, oversized bodies, notifications, conflict after expiration,
  and unidentified-sandbox blocking.
- `backend/tests/integration/tests/craft/docker_e2e/test_approval_gate_docker.py`
  exercises approve/reject and unavailable-app behavior through the Docker
  proxy path.

Frontend tests and stories cover packet parsing, approval card states, payload
display, and scheduled-task pre-approval UI components.

## Operational Notes

Relevant config:

- `ENABLE_CRAFT=true` enables Craft chart resources.
- `SANDBOX_BACKEND` is `kubernetes` or `docker`.
- `SANDBOX_API_SERVER_URL` must be set for sandbox API calls and PAT injection.
- `SANDBOX_PROXY_HOST` and `SANDBOX_PROXY_PORT` tell sandboxes where to proxy.
- `SANDBOX_PROXY_LISTEN_PORT` and `SANDBOX_PROXY_HEALTHZ_PORT` configure the
  proxy process.
- `SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS` controls proxy park time and live
  approval lifetime. Default: 180.
- `SANDBOX_PROXY_CA_SECRET` and `SANDBOX_PROXY_CA_CONFIGMAP` name Kubernetes CA
  resources.

Local development:

- Kubernetes Craft development uses real sandbox pods. See
  `docs/craft/dev/local-kubernetes.md`.
- Docker backend and proxy-specific local development are covered in
  `docs/craft/dev/local-compose-craft.md`.
- Sandbox proxy changes require rebuilding the backend image, loading it into
  the local cluster, and restarting the proxy/API pods.
- Sandbox image, `firewall-init.sh`, or opencode plugin changes require
  rebuilding the sandbox image, loading it into the local cluster or Docker
  environment, and recycling sandbox pods/containers.
