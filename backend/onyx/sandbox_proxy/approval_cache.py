"""Ephemeral cache signals for the approval rendezvous.

The Postgres `action_approval` row is the source of truth; everything
here is best-effort over `CacheBackend`. Two lists:

* `approval:announce:{session_id}` — proxy RPUSHes after committing the
  row; the chat-stream merger BLPOPs to emit the card on the live SSE
  stream. A miss degrades to the FE's next `/live` refetch.
* `approval:wake:{approval_id}` — api-server RPUSHes when a decision is
  recorded; the parked proxy BLPOPs to wake before `WAIT_TIMEOUT_S`.
"""

import asyncio
from uuid import UUID

from onyx.cache.interface import CacheBackend
from onyx.db.enums import ApprovalDecision

# Max time the proxy parks on one approval; also the `/live` window
# past which a `decision IS NULL` row is treated as orphaned.
WAIT_TIMEOUT_S = 180

# Only need to outlive the gap between RPUSH and the consumer's BLPOP.
ANNOUNCE_TTL_S = 60
WAKE_TTL_S = 30


def announce_key(session_id: UUID) -> str:
    return f"approval:announce:{session_id}"


def _wake_key(approval_id: UUID) -> str:
    return f"approval:wake:{approval_id}"


def announce_approval(approval_id: UUID, session_id: UUID, cache: CacheBackend) -> None:
    cache.rpush(announce_key(session_id), str(approval_id))
    cache.expire(announce_key(session_id), ANNOUNCE_TTL_S)


async def wait_for_wake(
    approval_id: UUID, timeout_s: int, cache: CacheBackend
) -> ApprovalDecision | None:
    """Block for a decision. `None` on timeout/unparseable payload (caller re-reads the row)."""
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


def send_wake(
    approval_id: UUID, decision: ApprovalDecision, cache: CacheBackend
) -> None:
    """Wake the parked proxy. A miss just means it waits out `WAIT_TIMEOUT_S`."""
    cache.rpush(_wake_key(approval_id), decision.value)
    cache.expire(_wake_key(approval_id), WAKE_TTL_S)


def pop_announcement(
    session_id: UUID, timeout_s: int, cache: CacheBackend
) -> UUID | None:
    """Synchronous BLPOP; runs in a producer thread feeding the chat-stream merge queue."""
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
