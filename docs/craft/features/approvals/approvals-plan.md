# Craft Approvals — Project Proposal

> **Review status.** [Phase 1](./phase-1-proxy.md) has been reviewed
> in detail and is the document to trust for implementation specifics.
> [Phase 2](./phase-2-service-and-gating.md),
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
chat within that window can still act. The proxy enforces a single
internal wait timeout (default 180s) — users have ~3 minutes to decide.
Past that, the proxy writes a terminal state on the approval row and
returns `403 not_authorized` to the sandbox. If the sandbox-side socket
closes first (SDK timeout shorter than 180s), the proxy still marks the
row as expired before its coroutine exits — pending rows never linger
just because a TCP connection went away. We do not preserve approvals
beyond the live request — there's nothing for an approval to drive once
the agent has moved on.
- **Single source of truth.** All trigger sources write to the same Approval
Service, surface in the same UI, respect the same policy.
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
                                2. │    │ 4b. relay
                                   ▼    │    decision
                           ┌────────────────────┐ 3. notify  ┌──────────────┐
                           │    API Server      ├───────────►│   Chat UI    │
                           │ (Approval Service) │            │ user decides │
                           │                    │◄───────────┤              │
                           └────────────────────┘ 4a. POST   └──────────────┘
                                                  decision
```

The numbered steps:

1. The Craft agent makes an outbound HTTPS request; the proxy intercepts.
2. The proxy matches it against a gated action and calls the Approval
  Service.
3. The Approval Service notifies the user.
4. The user decides via the chat UI (4a). The Approval Service relays the
  decision back to the proxy (4b).
5. The proxy forwards the original request to the external API (5a) or
  returns 403 to the sandbox (5b).

Scheduled-task-driven sessions (cron-initiated prompts) flow through the  
same path.

Policy is a config hierarchy, not a service: developer-defined actions, with
admin per-action policy on top (require / deny / always allow), evaluated by
the Approval Service at decision time. The schema is built so per-user
overrides can slot in later, but v0 ships admin-only.

The proxy MITMs sandbox HTTPS so it can identify gated actions from URL and
body. The Approval Service is the system of record — stores approvals,
evaluates policy, dispatches notifications, exposes the decision API.
Independent of trigger source: anything that calls `create_approval` ends up
in the same chat card.

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

### Phase 2 — Approval Service & Gate Wiring

The backend service plus the proxy's first real job. Two parts:

- **Approval Service.** Data model, state machine, REST API. Decision
endpoint, audit query path, internal Python API consumed by triggers.
`APPROVAL_REQUESTED` notifications via the existing notification system.
- **Gate wiring in the proxy.** The proxy starts matching requests against
the gated-action registry — which is owned by the External Apps
workstream on `dane/ea-craft-5` (its `upstream_url_patterns` per provider
is the source of truth for what each action looks like on the wire). We
consume that registry rather than redefine matchers here. When a match
fires, the proxy calls the service, blocks the request until a decision
lands or its internal wait timeout (default 180s) elapses, and forwards,
rejects, or returns `403 not_authorized` accordingly. If the sandbox-side
socket closes first, the proxy still writes a terminal state on the row
so it doesn't linger as `pending`.
- **Bash-tool timeout + agent prompt.** Verify opencode's default bash-tool
timeout and raise it to ≥240s so it doesn't dominate the proxy's 180s
wait for `curl`-style calls. Add a sentence to the agent's system prompt
explaining the approval window so the LLM sets generous explicit timeouts
on gated calls.

Deliverable: gated external-app requests work end-to-end. Users decide via
notification deep link until Phase 3 lands the chat surface.

### Phase 3 — Chat Approval UI

Inline approval card in the chat: summary, structured payload, Approve /
Reject buttons. Persisted on the conversation. The card is interactive
while the underlying request is still in flight; once the request has
timed out, the card shows a terminal state (expired / not authorized) and
the buttons are disabled.

Deliverable: approve / reject inline; no notification round-trip.

### Phase 4 — Policy Management

Developer-defined action registry and an admin settings page for per-action
org-wide policy (require / deny / always allow). Policy evaluation moves
out of any hardcoded constant and into the Approval Service so all triggers
share it. The schema is structured for a future per-user override layer
but the UI is admin-only in v0.

Deliverable: requirements met in full.

### Phase 5 — Docker-compose backend support

Run the same proxy against the docker-compose sandbox backend
(`SANDBOX_BACKEND=docker`). The proxy core, gate logic, Approval
Service, chat UI, and policy layer are unchanged from Phases 1–4 —
this phase is exclusively the infrastructure delta: a Docker-events-
based identity-resolver source slotting into the Phase 1 interface,
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
specific. The approval row is still marked terminal in either case.
Accepted for v0; UX must make the notification noticeable so users
decide before any timeout fires.
- **Bash-tool harness timeout is a third bound.** When the agent issues
HTTPS via `curl` or similar through opencode's bash tool, the harness
kills the spawned process at its own timeout (default needs verification;
likely 60–120s). That timer dominates the proxy's 180s wait for any
bash-mediated request. Mitigations: raise opencode's bash-tool default
timeout to ≥240s so the proxy wait dominates, and instruct the agent in
its system prompt to set a generous explicit timeout on gated calls.
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

