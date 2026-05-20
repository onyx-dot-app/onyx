# Session Resolution for Approval Routing

How the egress proxy decides which `BuildSession` an approval card belongs to, and what we considered before settling on the v0 approach.

## Decision (v0)

The proxy uses a **most-recent-active heuristic**: sandbox IP → `Sandbox` row → `sandbox.user_id` → the user's `BuildSession` with `status == ACTIVE` and the most recent `last_activity_at`. ("Sandbox IP" is the K8s pod IP or the docker container's bridge IP, depending on backend — Phase 1's `SandboxIPLookup` Protocol abstracts the difference.) The exact rule lives in `phase-1-proxy.md` §"Sandbox → session resolution rule."

## Why it works for v0

In typical Craft usage, a user has one active session at a time. Messages are processed sequentially; `last_activity_at` cleanly identifies the session the user is currently working in. The card lands in the right place by default.

## Known limitation

The heuristic fails when a user has multiple concurrent active sessions on the same sandbox. The most common case:

- An interactive chat session AND a scheduled-task-triggered session both active at the same time.

(Two simultaneously-processing interactive sessions are also possible — the Craft sidebar supports multiple sessions per user — but less common.)

When this happens, the approval card lands in whichever session's `last_activity_at` is more recent at the moment the proxy resolves. This can race with whichever session is being interacted with.

The failure mode is **UX confusion, not a security issue**:

- The card always lands in *some* session belonging to the correct user.
- The action payload identifies what is being approved.
- The user can inspect and decide as normal.
- But the card may render in a chat tab unrelated to the session that originated the request.

We accept this for v0 because:

1. Concurrent same-user active sessions are uncommon in early Craft usage.
2. The failure mode is contained (right user, possibly wrong chat tab).
3. Both stricter alternatives carry real cost — described below.

## Alternatives considered

### Per-session listening port at the proxy

The proxy allocates a unique listening port per `BuildSession`. Opencode for that session is launched with `HTTPS_PROXY` pointing at that port. The proxy maps listening port → session, optionally cross-checked against pod IP → user.

**What it would have bought us:** precise card routing by default. Each outbound HTTPS call arrives on the originating session's port; no ambiguity in the common case.

**Why we did not ship this in v0:** the identity is not strictly enforced. `HTTPS_PROXY` is a userland convention. The agent or a flawed skill could override it and connect to a different session's port. A cross-check (sandbox IP → user must match port → session user) prevents cross-user impersonation, but within-user misrouting remains possible. Adding the operational complexity of per-session port allocation, listener configuration, and lifecycle to get a non-strict identity didn't feel worth it — we either wanted a strict mechanism or were willing to live with the heuristic.

### Per-session UID + iptables marking + mitmproxy

Allocate a distinct Linux UID per `BuildSession`. A launcher binary drops to that UID before `exec`-ing opencode. A privileged sidecar installs iptables `OUTPUT` rules with `-m owner --uid-owner` that mark egress packets with the session's UID. The proxy reads the fwmark (or routes via per-UID listening ports) to recover session identity.

(The constraints below are framed against K8s posture, which was the deployment target at the time. The docker-compose backend (Phase 5) faces a different but comparable cost model — extra entrypoint complexity, expanded container caps, gosu invocation per session — that doesn't change the heuristic-vs-strict trade-off.)

**What it would have bought us:** strict, kernel-enforced identity. The agent cannot change its UID without `CAP_SETUID` (which it does not have); iptables rules are installed by a privileged component the agent cannot reach; the network stack is the source of truth. This is the pattern Anthropic Claude Cowork reportedly uses for the same problem.

**Why we did not ship this in v0:**

1. **Incompatible with the planned `opencode serve` migration.** Under `opencode serve` (see `docs/craft/opencode-serve-migration.md`), a single long-lived opencode process runs per pod and handles every session for that user. All sessions share that process's UID; every skill subprocess inherits it. The per-message `kubectl exec` injection point that made the launcher pattern clean disappears. The workarounds — running one opencode-serve per session inside the pod, or modifying opencode upstream to setuid per session subprocess — carry real additional cost or depend on cooperation we don't directly control.
2. **Cluster posture cost.** The launcher container needs to run as root with `CAP_SETUID`; the iptables sidecar needs `CAP_NET_ADMIN`. Both conflict with PSS Restricted profiles and require namespace-level policy carve-outs. GKE Autopilot and OpenShift's default SCC reject this outright.
3. **For v0 traffic, the heuristic's failure mode is acceptable.** Strict identity becomes necessary when concurrent same-user sessions are common; in v0 they are not.

## How `opencode serve` invalidates these options

Both alternatives above were designed around opencode being launched per-message via `kubectl exec`. The planned migration to `opencode serve` (`docs/craft/opencode-serve-migration.md`) collapses that into one long-lived opencode process per pod that handles every session for the user. The launch-time injection point each option relied on disappears.

### What changes under `opencode serve`

- **One opencode-serve per pod, many sessions.** All sessions run inside the same long-lived process.
- **Skill subprocesses inherit opencode's UID and environment.** Every bash, curl, or python subprocess opencode spawns for any session runs under opencode's UID with opencode's env. There is no OS-level per-session distinction.
- **No per-session exec hook.** opencode is launched once at pod boot by the supervisor. There is no per-message command we can wrap with a launcher.

### Per-session port becomes harder

The mechanism required each session's opencode subprocess to have a distinct `HTTPS_PROXY` env. Under `opencode serve`, the env is set at opencode-serve startup and inherited by every skill subprocess regardless of which session triggered it. Post-migration, this option would require either (a) opencode itself setting a per-session `HTTPS_PROXY` when it spawns skill subprocesses (unclear whether opencode supports this), or (b) running one opencode-serve per session within the pod.

### Per-session UID becomes harder

The launcher pattern relied on a per-session exec point. Under `opencode serve`, all skill subprocesses inherit opencode's UID, so iptables `-m owner --uid-owner` cannot distinguish sessions. Post-migration, this option would require either (a) modifying opencode upstream to fork+setuid per session before spawning skill subprocesses, or (b) running one opencode-serve per session, each as a distinct UID.

### The shared workaround

Both options' fallback under `opencode serve` is the same: **run one opencode-serve per session, not one per pod.** This is a departure from the migration's "one per pod" architecture, but it's allowed by opencode itself — the SQLite corruption constraint that prevents sharing only applies to two processes pointing at the same data dir, and per-session data dirs are straightforward to provision.

Costs of one-opencode-per-session:

- Per-session memory overhead (opencode resident set multiplied by concurrent sessions).
- The supervisor in the sandbox container manages N processes instead of 1.
- The `opencode serve` migration doc would need to change accordingly.

The net effect: strict-identity becomes meaningfully more expensive to ship after the migration than before it. A future strict-identity design will need to choose between multiplying opencode processes per pod or waiting on upstream opencode cooperation.

## When to revisit

Reopen the strict-identity work when one of these triggers fires:

- The `opencode serve` migration completes, and we want session identity formalized at the proxy layer (the migration changes the architectural assumptions enough that a fresh design pass is needed).
- Customer reports of "the approval card showed up in the wrong chat" become non-trivial.
- Concurrent same-user sessions become a common workflow (heavy multi-tab usage, frequent scheduled-task fan-out overlapping with interactive use).

The per-session UID approach is the more durable answer of the two alternatives above and should be the starting point for a v1 design.
