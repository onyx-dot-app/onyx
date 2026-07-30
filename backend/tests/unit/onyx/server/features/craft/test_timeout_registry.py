"""Pins the Craft timeout registry: root values, derivations, and the
ordering invariants documented in ``onyx/server/features/build/timeouts.py``.

Value pins are the spec (hardcoded, not re-derived); relationship asserts are
the invariants that must survive any retuning of a root. Constants defined at
their point of use (single-file, free-standing) are imported from there.
"""

from onyx.server.features.build.configs import (
    OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS,
    PROMPT_SLOT_LEASE_SECONDS,
    SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS,
    SANDBOX_HEARTBEAT_REFRESH_INTERVAL_SECONDS,
    SANDBOX_IDLE_TIMEOUT_SECONDS,
    SSE_KEEPALIVE_INTERVAL,
)
from onyx.server.features.build.interactive_turns.api import (
    LIVE_STREAM_RUNNER_RETRY_SECONDS,
)
from onyx.server.features.build.interactive_turns.state import (
    TURN_LOCK_LEASE_SECONDS,
    TURN_LOCK_WAIT_SECONDS,
)
from onyx.server.features.build.timeouts import (
    ACTIVE_TURN_TTL_SECONDS,
    BULK_TRANSFER_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS,
    PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
    PROMPT_SLOT_KEEP_ALIVE_MAX_SECONDS,
    PROMPT_SLOT_WAIT_OUT_ORPHAN_SECONDS,
    QUEUE_RESIDENCY_SECONDS,
    REQUEST_ID_TTL_SECONDS,
    RPC_TIMEOUT_SECONDS,
    RUNNER_STALE_AFTER_SECONDS,
    TURN_BUDGET_SECONDS,
)


def test_root_values_pin_the_spec() -> None:
    assert TURN_BUDGET_SECONDS == 30 * 60
    assert QUEUE_RESIDENCY_SECONDS == 15 * 60


def test_turn_derivations() -> None:
    assert ACTIVE_TURN_TTL_SECONDS == 45 * 60
    assert REQUEST_ID_TTL_SECONDS == 60 * 60
    assert REQUEST_ID_TTL_SECONDS > ACTIVE_TURN_TTL_SECONDS
    # The identity is the spec: a slot held past any possible turn is leaked.
    assert PROMPT_SLOT_KEEP_ALIVE_MAX_SECONDS == TURN_BUDGET_SECONDS


def test_keepalive_derivations() -> None:
    # The coupling IS the spec: env-tuning the keepalive must move runner
    # staleness with it — a fixed stale threshold under a raised keepalive
    # steals turns from healthy silent tool calls. The literal pins the
    # multiplier and the default keepalive together.
    assert RUNNER_STALE_AFTER_SECONDS == 6 * SSE_KEEPALIVE_INTERVAL
    assert RUNNER_STALE_AFTER_SECONDS == 90.0
    assert LIVE_STREAM_RUNNER_RETRY_SECONDS < RUNNER_STALE_AFTER_SECONDS


def test_approval_inactivity_coupling() -> None:
    # A tool call parked at the approval proxy holds the event stream silent
    # for the full approval window; the inactivity backstop must outlast it.
    assert (
        OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS
        > SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
    )


def test_lock_invariants() -> None:
    assert PROMPT_SLOT_WAIT_OUT_ORPHAN_SECONDS > PROMPT_SLOT_LEASE_SECONDS
    assert PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS < PROMPT_SLOT_LEASE_SECONDS
    assert TURN_LOCK_WAIT_SECONDS < TURN_LOCK_LEASE_SECONDS


def test_ordering_chain() -> None:
    mutex_leases = (TURN_LOCK_LEASE_SECONDS, PROMPT_SLOT_LEASE_SECONDS)

    assert POLL_INTERVAL_SECONDS < CONNECT_TIMEOUT_SECONDS
    assert CONNECT_TIMEOUT_SECONDS < min(mutex_leases)
    assert max(mutex_leases) < QUEUE_RESIDENCY_SECONDS
    assert QUEUE_RESIDENCY_SECONDS < TURN_BUDGET_SECONDS
    assert TURN_BUDGET_SECONDS < ACTIVE_TURN_TTL_SECONDS
    assert ACTIVE_TURN_TTL_SECONDS < REQUEST_ID_TTL_SECONDS
    assert RPC_TIMEOUT_SECONDS < BULK_TRANSFER_TIMEOUT_SECONDS


def test_idle_family_invariants() -> None:
    # Heartbeat refresh must be far under the idle timeout or live sandboxes
    # read as idle between refreshes.
    assert (
        SANDBOX_HEARTBEAT_REFRESH_INTERVAL_SECONDS * 10 <= SANDBOX_IDLE_TIMEOUT_SECONDS
    )
