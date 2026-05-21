"""Ephemeral cache state for the approval rendezvous.

The Postgres `action_approval` row is the source of truth. Its
conditional `WHERE decision IS NULL` UPDATE is the only arbiter of
who wins a terminal write. Functions here are best-effort signals
over `CacheBackend` (Redis or Postgres-backed; either works).

Two single-purpose cache lists per coordination:

* `approval:announce:{session_id}` — the proxy `RPUSH`es an
  `approval_id` here right after committing the row. The api-server's
  chat-stream merger `BLPOP`s and emits an `ApprovalRequestedPacket`
  on the open SSE stream so the FE renders the card immediately. A
  missed announce stays correct because the FE refetches `/live` on
  reconnect / remount, but realtime fidelity depends on this path.

* `approval:wake:{approval_id}` — the api-server `RPUSH`es onto
  this when a decision is recorded. The parked proxy's `BLPOP`
  unblocks so it can write the response back to the sandbox without
  waiting out `WAIT_TIMEOUT_S`.
"""

import asyncio
from uuid import UUID

from onyx.cache.interface import CacheBackend
from onyx.db.enums import ApprovalDecision

# Outer bound on how long the proxy will park on a single approval.
# Also serves as the "is this row still actionable" window the
# `/live` endpoint applies — rows older than this with
# `decision IS NULL` are considered orphaned.
WAIT_TIMEOUT_S = 180

# A never-consumed announce / wake auto-evicts. The values only need
# to outlive the gap between RPUSH and the consumer's BLPOP.
ANNOUNCE_TTL_S = 60
WAKE_TTL_S = 30


def announce_key(session_id: UUID) -> str:
    return f"approval:announce:{session_id}"


def _wake_key(approval_id: UUID) -> str:
    return f"approval:wake:{approval_id}"


# ---------------------------------------------------------------------------
# Proxy side — announces new approvals, parks on the wake channel.
# ---------------------------------------------------------------------------


def announce_approval(approval_id: UUID, session_id: UUID, cache: CacheBackend) -> None:
    """Push an approval_id onto the session's announce list.

    Best-effort. A missed push degrades to "card surfaces only on the
    FE's next `/live` refetch (reconnect / remount)" — correctness
    is preserved, realtime is not.
    """
    cache.rpush(announce_key(session_id), str(approval_id))
    cache.expire(announce_key(session_id), ANNOUNCE_TTL_S)


async def wait_for_wake(
    approval_id: UUID, timeout_s: int, cache: CacheBackend
) -> ApprovalDecision | None:
    """Block until the api-server pushes a decision, or timeout.

    Returns the decoded decision, or `None` on timeout / unparseable
    payload (caller treats both as "re-read the row from Postgres").
    """
    result = await asyncio.to_thread(cache.blpop, [_wake_key(approval_id)], timeout_s)
    if result is None:
        return None
    _key, value = result
    if isinstance(value, bytes):
        value = value.decode()
    try:
        return ApprovalDecision(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# API side — pushes a decision onto the wake channel.
# ---------------------------------------------------------------------------


def send_wake(
    approval_id: UUID, decision: ApprovalDecision, cache: CacheBackend
) -> None:
    """Push a decision onto the wake channel for the parked proxy.

    Best-effort. A missed wake just means the proxy waits out
    `WAIT_TIMEOUT_S` and reads the winning decision from Postgres.
    """
    cache.rpush(_wake_key(approval_id), decision.value)
    cache.expire(_wake_key(approval_id), WAKE_TTL_S)


# ---------------------------------------------------------------------------
# Chat-stream merger side — drains announces during an active turn.
# ---------------------------------------------------------------------------


def pop_announcement(
    session_id: UUID, timeout_s: int, cache: CacheBackend
) -> UUID | None:
    """BLPOP one announce_id for the session, or `None` on timeout.

    Synchronous; intended to run in a producer thread feeding the
    chat-stream merge queue.
    """
    result = cache.blpop([announce_key(session_id)], timeout_s)
    if result is None:
        return None
    _key, value = result
    if isinstance(value, bytes):
        value = value.decode()
    try:
        return UUID(value)
    except ValueError:
        return None
