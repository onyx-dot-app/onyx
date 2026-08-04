"""Craft timeout registry.

Every Craft time constant is one of four things:

1. a **root** — a policy number a human chooses,
2. a **derivation** — arithmetic over a root, encoded here so tuning the root
   moves every dependent value with it,
3. the **fixed kit** — genuinely independent short timeouts in a small
   taxonomy (connect / RPC / bulk transfer / mutex lease), or
4. a **cadence** — poll and retry intervals.

Correctness never depends on any of these: a sandbox status write only
applies while the row still holds the writer's attempt number
(``provisioning_attempt_number``), and a turn write only applies for the owning
``runner_id``. Timeouts here only detect failure, bound budgets, or pace
polling.

Residence rule: a constant lives here only if it is used by multiple files,
is a derivation (or feeds one), or belongs to the shared client-I/O taxonomy.
A single-file, free-standing constant is defined at its point of use.
Env-tunable values (anything with its own ``os.environ`` read) live in
``configs.py`` even when their default is derived (e.g.
``OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS``); pure non-tunable derivations
over those roots live here (e.g. ``RUNNER_STALE_AFTER_SECONDS``).

Ordering invariants (asserted by
``tests/unit/onyx/server/features/craft/test_timeout_registry.py``):

    cadences < probes/connect < mutex leases < PROVISION_DEADLINE
      < ATTEMPT_DEADLINE (== observer staleness threshold)
      < QUEUE_RESIDENCY < TURN_BUDGET < ACTIVE_TURN_TTL < REQUEST_ID_TTL
    RUNNER_STALE_AFTER == 6 x SSE_KEEPALIVE_INTERVAL
    OPENCODE_PROMPT_INACTIVITY > SANDBOX_APPROVAL_WAIT (configs.py)
    SANDBOX_HEARTBEAT_REFRESH << SANDBOX_IDLE_TIMEOUT (configs.py)

The client-I/O taxonomy (connect / RPC / bulk) is orthogonal to the ordering
chain — a bulk transfer legitimately outlasts a provision deadline.
"""

from onyx.server.features.build.configs import (
    PROMPT_SLOT_LEASE_SECONDS,
    SSE_KEEPALIVE_INTERVAL,
)

# =============================================================================
# Provisioning family (root: PROVISION_DEADLINE_SECONDS)
# =============================================================================

# Max wall clock for one provision() call to converge a runtime. All internal
# phases (pod/container scheduling, history restore, readiness, opencode-serve
# bind, terminating-resource waits) draw from this one deadline. Also the
# provisioning lock's TTL: the lock never outlives the work it guards.
PROVISION_DEADLINE_SECONDS = 180.0

# Session-workspace materialization (template copy + bun install) inside an
# already-RUNNING sandbox. Enforced as an explicit exec deadline paired with a
# completion sentinel — the Kubernetes exec client returns truncated output
# without raising when its window lapses, so the sentinel is what
# distinguishes success from truncation.
WORKSPACE_SETUP_DEADLINE_SECONDS = PROVISION_DEADLINE_SECONDS

# Best-effort opencode-history capture before terminating an unhealthy
# sandbox. Small: recovery latency is user-facing and the history snapshot is
# a nice-to-have, not a gate.
RECOVERY_HISTORY_SNAPSHOT_SECONDS = 30.0

# Teardown of a dead runtime (Kubernetes deletes are async; this bounds the
# wait for resources to actually disappear).
RUNTIME_TEARDOWN_SECONDS = 30.0

# Everything a provisioning attempt spends outside provision() itself.
ATTEMPT_OVERHEAD_SECONDS = RECOVERY_HISTORY_SNAPSHOT_SECONDS + RUNTIME_TEARDOWN_SECONDS

# Self-enforced deadline of one provisioning attempt AND the observer-side
# staleness threshold: reconcile aborts (finalizing FAILED) at the same age at
# which reserve_sandbox declares a committed PROVISIONING row dead and takes
# it over, so a crashed attempt blocks its sandbox for at most this long. The
# check runs between external phases, so an in-flight phase can overrun it —
# takeover safety comes from the provisioning lock and the attempt-number
# condition on status writes, never from this number.
ATTEMPT_DEADLINE_SECONDS = PROVISION_DEADLINE_SECONDS + ATTEMPT_OVERHEAD_SECONDS

# How long POLL-policy callers wait out a concurrent live attempt before
# giving up. Sized to cover a typical full provision: failing earlier just
# fails a turn the concurrent attempt was about to satisfy.
PROVISION_WAIT_SECONDS = 120.0

# =============================================================================
# Turn family (root: TURN_BUDGET_SECONDS)
# =============================================================================

# Wall-clock budget of one agent turn, interactive or scheduled.
TURN_BUDGET_SECONDS = 30 * 60

# Margin past the budget before out-of-band cleanup (stuck-run sweeper, turn
# TTL expiry) treats a run/turn as abandoned: a well-behaved turn that hits
# its own budget must always finalize itself first.
TURN_RECLAIM_SLACK_SECONDS = 15 * 60

# Redis TTL of the turn record + active-turn pointer. Refreshed on every
# heartbeat; the absolute floor is the budget plus slack so a live
# budget-compliant turn's admission block never evaporates under it.
ACTIVE_TURN_TTL_SECONDS = TURN_BUDGET_SECONDS + TURN_RECLAIM_SLACK_SECONDS

# Post-terminal retention of the turn record and the client_request_id →
# turn_id dedupe key: an idempotent send-message retry (or the attach stream
# reading a FAILED turn's error) must still resolve after the turn finishes.
TURN_RETENTION_SECONDS = 15 * 60
REQUEST_ID_TTL_SECONDS = ACTIVE_TURN_TTL_SECONDS + TURN_RETENTION_SECONDS

# Ceiling for background prompt-slot renewal by holders whose progress is
# client-paced or opaque (session delete, subagent turns). It IS the turn
# budget: a slot held longer than any turn may run is leaked.
PROMPT_SLOT_KEEP_ALIVE_MAX_SECONDS = TURN_BUDGET_SECONDS

# =============================================================================
# Liveness cadence family (root: SSE_KEEPALIVE_INTERVAL, configs.py)
# =============================================================================

# A turn runner heartbeats on every consumed event, and the transport emits a
# keepalive at least every SSE_KEEPALIVE_INTERVAL even while the agent is
# silent — so the runner is dead after k missed keepalives, not after any
# turn-length-derived time. Derived so env-tuning the keepalive moves this
# with it; a fixed value would silently break turn recovery.
RUNNER_STALE_AFTER_SECONDS = 6 * SSE_KEEPALIVE_INTERVAL

# =============================================================================
# Queue residency family (root: QUEUE_RESIDENCY_SECONDS)
# =============================================================================

# One policy, three enforcement points: how long a queued scheduled run may
# sit before (a) Celery expires the message unexecuted and (b) the stuck-run
# sweeper reclaims its QUEUED row. They must move together or
# expired-but-unswept / swept-but-unexpired windows appear.
QUEUE_RESIDENCY_SECONDS = 15 * 60

# =============================================================================
# Fixed kit — client I/O taxonomy
# =============================================================================

# Establishing a connection to an in-cluster peer; also full-request probes
# on hot paths, where any response counts.
CONNECT_TIMEOUT_SECONDS = 5.0

# Unary request/response calls with small payloads (sidecar directory
# listings, managed-content pushes — the latter retried on failure).
RPC_TIMEOUT_SECONDS = 30.0

# Archive upload/download (session snapshots, opencode history). Sized to
# "snapshotting can take minutes"; the reaper is fail-closed on snapshot
# failure, so shrinking this converts slow-but-working snapshots into
# never-sleeping sandboxes.
BULK_TRANSFER_TIMEOUT_SECONDS = 300.0

# =============================================================================
# Fixed kit — mutexes (critical-section leases, never budget-derived)
# =============================================================================

# Session create/restore flow lock (one per-user lock shared by create,
# restore, and the reaper): held across one full session-flow operation —
# sandbox attempt + snapshot restore + workspace materialization — so the
# lease is the sum of those bounds. Deletable once the flows are crash-safe
# end-to-end without it.
SESSION_FLOW_LOCK_LEASE_SECONDS = (
    ATTEMPT_DEADLINE_SECONDS
    + BULK_TRANSFER_TIMEOUT_SECONDS
    + WORKSPACE_SETUP_DEADLINE_SECONDS
)

# Prompt-slot acquire policy: a second turn racing a live one bounces fast
# ("concurrent turn in flight") instead of queueing; a reclaimed turn must
# instead wait out a dead holder's full lease before taking the slot.
PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS = 10.0
PROMPT_SLOT_WAIT_OUT_ORPHAN_SECONDS = PROMPT_SLOT_LEASE_SECONDS + 10.0

# =============================================================================
# Cadences
# =============================================================================

# Shared interval for every poll-a-fast-local-resource loop (pod IP, container
# running, opencode-serve bind, resource deletion, PROVISIONING status,
# live-stream readiness).
POLL_INTERVAL_SECONDS = 0.5
