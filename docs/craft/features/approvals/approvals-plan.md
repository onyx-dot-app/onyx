# Craft Approvals — Project Proposal

> **Review status.** [Phase 1](./phase-1-proxy.md) and
> [Phase 2](./phase-2-service-and-gating.md) have been reviewed in
> detail and are the documents to trust for implementation specifics.
> [Phase 3](./phase-3-chat-ui.md), [Phase 4](./phase-4-policy.md),
> and [Phase 5](./phase-5-docker.md) are **rough proposals** —
> directionally correct, but the task-level detail has not been
> through the same review pass. Expect refactoring of those plans
> before implementation begins.

## Summary

Craft agents can take actions in external systems without user oversight. This
proposal adds an approval gate at the egress boundary so users confirm
sensitive actions before they execute. Approvals integrate with chat (inline
cards), with scheduled tasks (pause until decided), and with a layered policy
model (developer-defined actions, admin per-action policy). The gate
lives in the egress interception layer, which subsequent workstreams will
extend with secret injection and broader policy.

---

## Problem

Agents in Craft can take actions in external systems with no user oversight.
Three product workstreams need to gate this — external apps, scheduled tasks,
and developer-defined built-in actions — and would otherwise build the same
mechanism three times.

---

## Goals & Requirements

### Functional

1. **External-app requests** initiated by an agent (Slack, Linear, GCal in v0)
  trigger an approval UI in the user's chat session before the request is
   forwarded.
2. **Scheduled-task-driven sessions** (a cron sends a prompt into a session)
  gate network requests the same way as interactive sessions — the proxy
   doesn't distinguish them. Pending approvals surface as notifications and
   persist on the chat for when the user returns.
3. **Developers** define gated actions in code. Each action declares what it
  is and how its summary renders.
4. **Admins** set org-wide policy per gated action:
  - **Require approval** (default): users are prompted each time.
  - **Deny**: action is blocked without prompting.
  - **Always allow**: action proceeds silently.
   The policy schema is structured so per-user overrides can be layered on
   later without a rewrite — v0 ships org-wide only.
5. **Auditability**: every approval, including silent allows, denials, and
  expirations, is recorded and queryable.

### Non-functional

- **Sandboxes are blind to approvals.** Skill code, agent code, and opencode
do not need to know approvals exist.
- **Approval lifetime = request lifetime.** The approval is actionable while
the underlying sandbox request is still in flight. Closing the chat does
not kill the request (the proxy holds it open), so a user who reopens the
chat within that window can still act. A single coordination constant
— `WAIT_TIMEOUT_S = 180` in
`backend/onyx/sandbox_proxy/approval_cache.py` — bounds both the proxy's
park time and the "still actionable" window the `/live` endpoint applies.
Users have ~3 minutes to decide. Past that, the proxy writes a terminal
state on the approval row and returns `403 not_authorized` to the
sandbox. If the sandbox-side socket closes first (SDK timeout shorter
than 180s), the proxy still marks the row as expired before its
coroutine exits — pending rows never linger just because a TCP
connection went away. We do not preserve approvals beyond the live
request — there's nothing for an approval to drive once the agent has
moved on.
- **Single source of truth.** All trigger sources write to the same
`action_approval` table, surface in the same UI, respect the same
policy.
- **Forward-compatible with the full interception layer.** The proxy here is
the seed of a larger workstream (secret injection, broader policy). Same
monorepo, same package, same data layer.

### Out of Scope

- Secret injection (next interception-layer workstream).
- Non-HTTP egress (gRPC, raw TCP).
- Local-sandbox support (`SANDBOX_BACKEND=local`); local Craft has no
  realistic blast radius and there's no customer driver. Kubernetes
  and docker-compose backends are both in scope (Phases 1 and 5
  respectively).
- Opencode-native tool gating (bash, file ops); separate mechanism, deferred.

---

## Why a Proxy Layer

Two facts shape the design:

- We already need an egress proxy for secret injection — it's the next
interception-layer workstream and will exist regardless of approvals.
- We want approvals on arbitrary actions the LLM writes ("any write to
Slack," not a curated list of skill calls), which requires inspecting
the actual HTTPS request, not the agent's tool-call surface.

Putting approvals in the shared proxy layer is the natural fit: it's the
one place that sees every outbound request, can identify the action from
URL and body, and will already be handling secrets on the same path.
Approvals become a feature of the interception layer rather than a separate
mechanism.

**Trade-off worth naming.** Gating at the request level means the approval
window is bounded by the sandbox's HTTP client timeout (typically 30–120s).
Tool-call-level interception — what Claude does with MCP, where approval is
gated at the tool-call protocol layer — can give the user up to 5 minutes
because the "tool call" is a protocol concept, not a real network request
with its own socket timeout. We accept the tighter window in exchange for
being able to gate arbitrary LLM-driven HTTPS requests, not just a curated
set of tool definitions.

**mitmproxy is the preferred implementation for the proxy.** It's the dominant
OSS choice for HTTPS interception in agent sandboxes — precedents include
`agentcage`, `mattolson/agent-sandbox`, and the `danisla/kubernetes-tproxy`
Helm reference. Native MITM, Python addon API, modest LOC for the v0 surface.
Heavier alternatives (Envoy with `ext_authz`, custom Go proxies of the
Anthropic Cowork / Cloudflare Sandboxes shape) are documented industry
choices once a deployment outgrows Python — a transition we're not close to.

---

## Architecture

```
   ┌─────────────┐ 1. request   ┌───────────┐  5a. forward ┌──────────────┐
   │ Sandbox     ├─────────────►│  Proxy    ├─────────────►│ external API │
   │             │              │           │              └──────────────┘
   │(Craft agent)│ ◄────────────┤(mitmproxy)│
   └─────────────┘ 5b. 403      └──┬────▲───┘
                  (on reject)      │    │
                                2. │    │ 4b. wake
                                   ▼    │
                           ┌────────────────────┐ 3. notify  ┌──────────────┐
                           │    API Server      ├───────────►│   Chat UI    │
                           │                    │            │ user decides │
                           │                    │◄───────────┤              │
                           └────────────────────┘ 4a. POST   └──────────────┘
                                                  decision
```

The numbered steps:

1. The Craft agent makes an outbound HTTPS request; the proxy intercepts.
2. The proxy matches it against a gated action, commits an
   `action_approval` row, pushes the new `approval_id` onto the
   session's announce list (`approval:announce:{session_id}`), and
   parks on a per-approval wake channel
   (`approval:wake:{approval_id}`).
3. The api-server's chat-stream merger is already holding an SSE open
   for the active agent turn. It drains the announce list and emits an
   `ApprovalRequestedPacket` through the existing stream so the FE
   renders the card immediately. A fallback `APPROVAL_REQUESTED`
   notification is also dispatched (body carries only
   `{approval_id, session_id, action_type}` — no payload contents).
4. The user decides via the chat UI (4a). The API records the decision
   via a conditional `WHERE decision IS NULL` UPDATE, then pushes the
   decision onto the wake channel (4b) so the proxy unblocks without
   waiting out its 180s timeout.
5. The proxy forwards the original request to the external API on
   APPROVED (5a) or returns a 403 to the sandbox on REJECTED / EXPIRED
   (5b).

Scheduled-task-driven sessions (cron-initiated prompts) flow through the
same path.

### Data flow specifics

- **Postgres `action_approval` is the single source of truth.** The
  row's `decision` column starts as `NULL` and is written exactly once
  by a conditional `UPDATE ... WHERE decision IS NULL RETURNING *`
  (`try_record_decision` in
  `backend/onyx/server/features/build/db/action_approval.py`). That
  conditional UPDATE is the only arbiter for concurrent decision
  writers — the API server's approve / reject and the proxy's
  timeout / SIGTERM-drain expiry all race through it. Liveness is a
  pure SQL predicate: `decision IS NULL AND created_at >= now() -
  INTERVAL 'WAIT_TIMEOUT_S'`. Rows older than the wait window with
  `decision IS NULL` are treated as orphaned (the proxy that parked
  on them is gone and can no longer write EXPIRED) and excluded from
  the `/live` feed. There is no heartbeat key, no presence flag, no
  separate liveness signal — Postgres + a clock is the entire story.
- **`ApprovalDecision` enum** (`backend/onyx/db/enums.py`) has three
  values: `APPROVED`, `REJECTED`, `EXPIRED`. There is **no `PENDING`
  value**; pending is represented by `decision IS NULL`. Clients can
  only submit `APPROVED` or `REJECTED`; `EXPIRED` is server-only,
  written by the proxy on timeout or SIGTERM drain.
- **Two Redis lists for cross-process coordination** (defined in
  `backend/onyx/sandbox_proxy/approval_cache.py`, both best-effort,
  both tenant-prefixed via `get_cache_backend(tenant_id=...)`):
  - `approval:announce:{session_id}` — proxy → api-server. The gate
    `RPUSH`es the `approval_id` immediately after committing the
    row; the api-server's chat-stream merger `BLPOP`s during the
    open SSE turn. A missed announce degrades to "the FE refetches
    `/live` on reconnect or remount" — correctness is preserved,
    realtime is not. TTL 60s on the list.
  - `approval:wake:{approval_id}` — api-server → proxy. On a
    successful decision write the API `RPUSH`es the decision string
    onto this list so the parked proxy's `BLPOP` unblocks instead
    of waiting out `WAIT_TIMEOUT_S`. A missed wake just means the
    proxy waits out the timeout and reads the winning decision from
    Postgres. TTL 30s.
- **Cache module functions** split by role:
  - Proxy side: `announce_approval`, `wait_for_wake`.
  - API side: `send_wake`.
  - Chat-stream merger side: `pop_announcement`.
- **Tenant isolation** rides the existing infra: the cache backend
  applies a per-tenant Redis key prefix (callers pass `tenant_id`),
  and per-tenant Postgres schemas isolate DB rows. The gate addon,
  decision API, and chat-stream merger all obtain a `CacheBackend`
  via `get_cache_backend(tenant_id=...)`.
- **Coordination constants.** `WAIT_TIMEOUT_S = 180` is the only
  knob shared across processes — proxy park time, `/live` cutoff,
  and (transitively) the FE card's effective lifetime. The
  announce-list `BLPOP` inside the merger uses a `timeout_s=1` so
  the producer thread is responsive to merger shutdown; this is an
  internal pacing knob, not a coordination bound.

### Chat surface integration

- **Approvals are not BuildMessages.** The chat surface fetches live
  approvals via `GET /api/build/approvals/sessions/{id}/live` — a
  separate endpoint that returns rows where `decision IS NULL` AND
  `created_at >= now() - WAIT_TIMEOUT_S`. Orphan rows left by a
  hard proxy crash naturally drop off the feed when their
  `created_at` ages past the cutoff.
- **Realtime discovery piggybacks on the chat SSE stream.** The
  agent turn endpoint already holds an SSE open while the agent is
  running. `BuildSessionManager._merge_acp_with_announces`
  (`backend/onyx/server/features/build/session/manager.py`)
  interleaves ACP events with announce-list pops via two daemon
  threads writing onto a shared `queue.Queue`: one drives the ACP
  iterator, one `BLPOP`s `approval:announce:{session_id}` and
  emits `ApprovalRequestedPacket` instances (defined in
  `backend/onyx/server/features/build/packets.py`) into the
  same stream. The packet carries only `{approval_id, session_id}`
  — Postgres remains the source of truth for card contents. On the
  FE, `useBuildStreaming` invalidates the
  `SWR_KEYS.buildSessionLiveApprovals(sessionId)` cache key on
  receipt and `useSWR` consumers refetch automatically.
- **Fallback discovery for users not in the active SSE.** A
  best-effort `APPROVAL_REQUESTED` notification is also dispatched
  from the gate addon so users who reopen the chat later see the
  pending card. The FE's own `useSWR` refetch on remount /
  reconnect picks up anything the realtime path misses.
- **After resolution the card disappears.** The agent's subsequent
  tool-call BuildMessage is the only permanent chat record of the
  action's outcome (success on APPROVED, the sandbox's handling of
  the 403 on REJECTED / EXPIRED). There is no `is_live` field on
  `MessageResponse`; the `is_live` field on `ApprovalView` is
  derived per-response from `decision IS NULL AND created_at >=
  cutoff`.
- **Audit history is a sibling endpoint.**
  `GET /api/build/approvals/sessions/{id}` returns the full history
  filterable by `decision`, `since`, `until`.

### Failure-mode posture

The gate addon (`backend/onyx/sandbox_proxy/addons/gate.py`) takes a
deliberate split posture between fail-closed and fail-open:

- **Fail-closed (returns 403, no upstream call).**
  - No source IP on the TCP connection → 403 `unidentified_sandbox`.
  - Identity resolver raises → 403 `unidentified_sandbox`. Identity is
    a precondition for gating; a DB blip cannot grant ungated egress.
  - `flow.request.raw_content is None` → 403 `body_too_large`.
    Defensive against a future addon enabling `stream=True`.
  - Request body exceeds 1 MiB (`PARSER_MAX_BODY_BYTES`) → 403
    `body_too_large`. A real DoS attempt against the matcher or
    exfiltration wouldn't show up in the action summary anyway.
- **Fail-open (forwards unchanged).**
  - `ActionMatcher.match(...)` raises → log `gate.matcher_error`,
    forward. Deliberate: the gate is a UX layer plus audit trail, not
    a sandbox boundary. The real boundary is the in-pod iptables
    egress lockdown that Phase 1 installs.
- **Sandbox-facing 403 code enum** (locked, separate protocol from
  `OnyxError`):
  `unidentified_sandbox | body_too_large | user_rejected | not_authorized | internal_error`.
  `policy_denied` is reserved for Phase 4. The body is
  `json.dumps({"error": code, "message": prose})` with
  `content-type: application/json` — `error` is the stable code tooling matches
  on, `message` is human-readable prose the sandbox agent acts on.

### SIGTERM drain

The proxy bundles the backend module tree and runs alongside in-pod
iptables, so a graceful shutdown matters: dropping a connection
mid-wait without writing a terminal decision would leave a row in
`decision IS NULL` indefinitely (until the next admin audit query),
and dropping a connection on an already-APPROVED row without
forwarding upstream would make the audit log lie.

The drain (`GateAddon.drain_inflight` →
`backend/onyx/sandbox_proxy/server.py::_install_signal_handlers`)
runs in two phases.

Phase 1. For every entry in `_parked_approvals` (the `approval_id →
tenant_id` dict the gate maintains for every in-flight park):

1. Issue the same conditional UPDATE the timeout path uses
   (`_claim_expired_or_read_winner`). Win → row is EXPIRED. Lose →
   re-read and use the API's already-written decision.
2. `send_wake(approval_id, decision, …)` so the parked `BLPOP`
   returns immediately instead of waiting out `WAIT_TIMEOUT_S`.

Phase 2. `asyncio.wait` on `GateAddon._inflight_tasks` — every
`request()` coroutine registers itself there on entry — so the drain
actually blocks until each parked coroutine has serialized its
response (including any upstream forward on APPROVED) before
mitmproxy tears connections down. The outer cap is `_DRAIN_TIMEOUT_S
= 10.0` in `server.py` so a stuck DB / Redis call can't hang
shutdown indefinitely. The deployment's
`terminationGracePeriodSeconds` sizes to bound the outer window —
`_DRAIN_TIMEOUT_S + margin`, i.e. ≥ 20s.

Policy is a config hierarchy, not a service: developer-defined actions, with
admin per-action policy on top (require / deny / always allow), evaluated by
the policy layer at decision time. The schema is built so per-user
overrides can slot in later, but v0 ships admin-only.

The proxy MITMs sandbox HTTPS so it can identify gated actions from URL and
body. Trigger sources (gate addon, scheduled-task entrypoint, policy
evaluator) all write to the same `action_approval` table, so anything
that wants to surface in chat or in audit history goes through the
same code path.

---

## Phasing

Each phase delivers value and unblocks the next.

### Phase 1 — Egress Interception Proxy

Stand up the proxy as infrastructure, in pass-through mode (no gating
yet). This is the foundation everything else builds on. Phase 1 also
lands the **backend-swappable interfaces** (`SandboxIPLookup`,
`CAStore`, `firewall-init.sh` mode switch) that [Phase 5](#phase-5--docker-compose-backend-support)
plugs the docker implementations into. Concretely:

- The proxy itself, built on mitmproxy in a new `sandbox_proxy/` package.
- **In-pod iptables egress lockdown** installed by a privileged
  initContainer at pod startup: default-deny `OUTPUT`, allow only TCP to
  the proxy, drop DNS and IPv6. The initContainer self-verifies the
  lockdown before exiting; if rules aren't actually in effect, init
  fails and the pod doesn't start (fail-closed by construction). The
  alternative — a K8s NetworkPolicy at the CNI layer — was rejected
  because it fails *open* if the cluster's CNI ever stops enforcing,
  and didn't cover DNS or IPv6 in any case. Requires `CAP_NET_ADMIN`
  on the initContainer (PSS Baseline disallows added caps by default;
  a capability exception or a less-strict profile is required).
- **CA distribution to heterogeneous trust stores.** Proxy auto-generates
  its CA at bootstrap (persisted via the `CAStore` interface — K8s
  Secret in Phase 1, named volume in Phase 5) and publishes the
  public cert via a ConfigMap. The same initContainer above runs
  `update-ca-certificates` to install the cert into the system trust
  store. Node (`NODE_EXTRA_CA_CERTS`), Python `requests`
  (`REQUESTS_CA_BUNDLE`), AWS SDK (`AWS_CA_BUNDLE`), and Go
  (`SSL_CERT_FILE`) each consult their own trust mechanism; pod env
  must fan these out. Any SDK we haven't explicitly configured will
  fall through to its bundled CAs, reject the proxy's leaf cert, and
  fail closed at the iptables lockdown.
- **Identity resolution** via TCP source IP. Source IP is
  auto-attached by the kernel and un-spoofable by the agent. The
  proxy resolves `source_ip → sandbox → session` via the
  `SandboxIPLookup` Protocol (K8s informer-backed cache in Phase 1;
  Docker events stream in Phase 5) and a DB lookup for the active
  `BuildSession`. Rejected alternatives are spoofable or overkill
  respectively for v0.

Deliverable: all sandbox HTTPS traffic flows through the proxy, MITM'd,
identifiable to a session, and passed through unmodified. Security posture
improved (single chokepoint, default-deny) but no approval logic yet.

### Phase 2 — Approval Data Layer, API & Gate Wiring

The backend data layer, decision API, and the proxy's first real job.
Three parts:

- **Data + API.** A single `action_approval` table whose `decision`
  column is nullable (`NULL` = pending);
  `backend/onyx/server/features/build/db/action_approval.py` is the
  single source of SQL; the conditional `WHERE decision IS NULL`
  UPDATE in `try_record_decision` is the race-safe arbiter. The
  user-facing API
  (`backend/onyx/server/features/build/approvals/api.py`) exposes
  three endpoints: live-rows feed for chat, audit query, decision
  write. Idempotent same-value double-clicks on `/decision` return
  200; a different-value submission against an already-decided row
  raises `CONFLICT`.
- **Gate wiring.** The proxy stops being pass-through. The gate
  addon resolves the sandbox identity directly per request via
  `self._identity.resolve(src_ip)`, classifies the request through
  `ActionMatcher`, commits the `action_approval` row, pushes the
  `approval_id` onto the session's announce list, and parks on
  `approval:wake:{approval_id}` until a decision lands or the
  `WAIT_TIMEOUT_S` wait elapses, then forwards or rejects. Race-safe
  timeout / cancel / drain paths all flow through the same
  conditional UPDATE.
- **Bash-tool timeout + agent prompt.** Opencode's bash-tool timeout
  config is outside our control in this repo (opencode is consumed
  as a binary). The mitigation is a sentence in the agent's system
  prompt — `AGENTS.md` — telling the LLM to set explicit per-call
  timeouts ≥200s on gated HTTP calls so the proxy's 180s wait wins.

Deliverable: gated external-app requests work end-to-end. Users decide via
notification deep link until Phase 3 lands the chat surface.

### Phase 3 — Chat Approval UI

Inline approval card in the chat. Discovery is realtime: the existing
chat SSE stream interleaves `ApprovalRequestedPacket` events from
`_merge_acp_with_announces`, and the FE invalidates
`SWR_KEYS.buildSessionLiveApprovals(sessionId)` on receipt so the
`useSWR` consumer refetches `/approvals/sessions/{id}/live` and the
card mounts. The card renders summary, structured payload, and
Approve / Reject buttons. It is interactive while the underlying
request is still in flight; once the row goes terminal (any of
APPROVED / REJECTED / EXPIRED) the card disappears. The permanent
chat record of the action's outcome is the agent's subsequent
tool-call BuildMessage, not the approval card.

Deliverable: approve / reject inline; no notification round-trip.

### Phase 4 — Policy Management

Developer-defined action registry and an admin settings page for per-action
org-wide policy (require / deny / always allow). Policy evaluation lives
on the same code path so all triggers share it; the silent-decision
write goes through `insert_silent_action_approval` (audit row with
no liveness key and no chat card). The schema is structured for a
future per-user override layer but the UI is admin-only in v0.

Deliverable: requirements met in full.

### Phase 5 — Docker-compose backend support

Run the same proxy against the docker-compose sandbox backend
(`SANDBOX_BACKEND=docker`). The proxy core, gate logic, data layer,
API, chat UI, and policy layer are unchanged from Phases 1–4 — this
phase is exclusively the infrastructure delta: a Docker-events-based
identity-resolver source slotting into the Phase 1 interface,
shared-volume CA distribution, the same `firewall-init.sh` bootstrap
script run as the docker container's entrypoint wrapper instead of as
a K8s initContainer, and the proxy delivered as a compose service.

Phase 1 lands the swappable interfaces (`SandboxIPLookup`, `CAStore`,
the `SANDBOX_PROXY_BOOTSTRAP_MODE` switch in `firewall-init.sh`) so
this phase is a slot-in rather than a refactor of shared modules.

Deliverable: docker-compose Craft deployments get the same gating
behavior as K8s.

---

## Open Decisions

None outstanding. The action-kind taxonomy is locked in [Phase 4 T4.2](./phase-4-policy.md).

---

## Risks

- **Two-replica K8s proxy is not full HA; docker-compose ships single-instance.**
v0 K8s ships `replicas: 2` so a rolling deploy or single-replica
crash doesn't take down all egress — the survivor keeps accepting
new connections. In-flight flows on a crashed replica still drop
without resumption; the user re-prompts. The docker-compose deploy
(Phase 5) ships single-instance; the same crash drops in-flight
flows and briefly refuses new connections until `restart:
unless-stopped` brings the proxy back. True HA (cross-replica flow
handoff) is a future workstream for both backends.
- **Structured-error guarantee depends on SDK socket timeouts.** The proxy
returns `403 not_authorized` cleanly when its 180s wait fires first. For
SDKs (or agent code) that set socket timeouts shorter than 180s, the
sandbox-side client closes the connection first and the agent sees a
generic transport error instead of a structured response. The LLM
handles both — transport errors are common — but the signal is less
specific. The approval row is still marked terminal in either case
(the gate's `CancelledError` branch claims EXPIRED through the same
conditional UPDATE). Accepted for v0; UX must make the notification
noticeable so users decide before any timeout fires.
- **Bash-tool harness timeout is a third bound.** When the agent issues
HTTPS via `curl` or similar through opencode's bash tool, the harness
kills the spawned process at its own timeout. Opencode's bash-tool
timeout config lives outside this repo — opencode is consumed as a
binary we don't control. Mitigation is the AGENTS.md system-prompt
note telling the agent to set explicit per-call timeouts ≥200s on
gated HTTP calls; we can't change the harness default.
- **Trust-store fragmentation.** Each non-system-trust-store SDK in the
sandbox needs explicit env-var configuration to honor the proxy CA.
Untested SDKs fail closed at the in-pod iptables lockdown. Onboarding a
new gated SDK requires per-SDK verification.
- **Policy complexity creep.** Two-layer policy (developer-defined actions
  - admin per-action settings) is the right v0 model. Resist tier additions
  ("team-level," "project-level") without a clear product driver, and gate
  the user-level layer on a real customer signal.

---

## Future Work

- **User-level policy overrides.** Per-user per-action prefs layered over
the org policy; UI for users to opt into "always allow" within the
admin's bounds. Schema in v0 is built to accept this without rework.
- **Secret injection** — next workstream on the same proxy; closes the
bash-bypass loophole.
- **Opencode-native tool gating** via ACP `request_permission` for
destructive bash and file operations.
- **Resumability** of orphaned approvals — picking up an in-flight
approval whose proxy replica died. Requires cross-replica state for
the flow.
- **Higher-replica proxy + IP-lookup caching + Redis pool sizing** —
further scaling work tracked separately.
- **Local-sandbox support** if/when local Craft needs gating.
