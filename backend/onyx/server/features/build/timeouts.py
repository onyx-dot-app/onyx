"""Craft timeout registry.

Every Craft time constant is one of four things:

1. a **root** — a policy number a human chooses,
2. a **derivation** — arithmetic over a root, encoded here so tuning the root
   moves every dependent value with it,
3. the **fixed kit** — genuinely independent short timeouts in a small
   taxonomy (connect / RPC / bulk transfer / mutex lease), or
4. a **cadence** — poll and retry intervals.

Residence rule: a constant lives here only if it is used by multiple files,
is a derivation (or feeds one), or belongs to the shared client-I/O taxonomy.
A single-file, free-standing constant is defined at its point of use.
Env-tunable values (anything with its own ``os.environ`` read) live in
``configs.py`` even when their default is derived (e.g.
``OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS``); pure non-tunable derivations
over those roots live here (e.g. ``RUNNER_STALE_AFTER_SECONDS``).

Ordering invariants (asserted by
``tests/unit/onyx/server/features/craft/test_timeout_registry.py``):

    cadences < probes/connect < mutex leases
      < QUEUE_RESIDENCY < TURN_BUDGET < ACTIVE_TURN_TTL < REQUEST_ID_TTL
    RUNNER_STALE_AFTER == 6 x SSE_KEEPALIVE_INTERVAL
    OPENCODE_PROMPT_INACTIVITY > SANDBOX_APPROVAL_WAIT (configs.py)
    SANDBOX_HEARTBEAT_REFRESH << SANDBOX_IDLE_TIMEOUT (configs.py)

The client-I/O taxonomy (connect / RPC / bulk) is orthogonal to the ordering
chain — a bulk transfer legitimately outlasts most other bounds.
"""

from onyx.server.features.build.configs import (
    PROMPT_SLOT_LEASE_SECONDS,
    SSE_KEEPALIVE_INTERVAL,
)

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

# Prompt-slot acquire policy: a second turn racing a live one bounces fast
# ("concurrent turn in flight") instead of queueing; a reclaimed turn must
# instead wait out a dead holder's full lease before taking the slot.
PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS = 10.0
PROMPT_SLOT_WAIT_OUT_ORPHAN_SECONDS = PROMPT_SLOT_LEASE_SECONDS + 10.0

# =============================================================================
# Cadences
# =============================================================================

# Shared interval for poll-a-fast-local-resource loops (live-stream readiness;
# provisioning wait loops adopt it as they move onto the registry).
POLL_INTERVAL_SECONDS = 0.5
