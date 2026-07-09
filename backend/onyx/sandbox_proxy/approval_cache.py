"""Ephemeral cache signals for the approval rendezvous.

The Postgres `action_approval` row is the source of truth; everything
here is best-effort over `CacheBackend`. Two lists:

* `approval:announce:{session_id}` — proxy RPUSHes after committing the
  row; the chat-stream merger BLPOPs to emit the card on the live SSE
  stream. A miss degrades to the FE's next `/live` refetch.
* `approval:wake:{approval_id}` — api-server RPUSHes when a decision is
  recorded; the parked proxy BLPOPs to wake before the wait timeout.
"""

import asyncio
import time
from collections.abc import Iterable
from uuid import UUID

from onyx.cache.interface import CacheBackend
from onyx.db.enums import ApprovalDecision

# Only need to outlive the gap between RPUSH and the consumer's BLPOP.
ANNOUNCE_TTL_S = 60
WAKE_TTL_S = 30

# Session grant cache keys are an acceleration layer. The durable grant source is
# the action_approval row whose decision was recorded via SESSION_GRANT.
SESSION_GRANT_TTL_S = 60 * 60


def announce_key(session_id: UUID) -> str:
    return f"approval:announce:{session_id}"


def _wake_key(approval_id: UUID) -> str:
    return f"approval:wake:{approval_id}"


def _session_grant_key(session_id: UUID, external_app_id: int, action_type: str) -> str:
    return f"approval:session-grant:{session_id}:{external_app_id}:{action_type}"


def announce_approval(approval_id: UUID, session_id: UUID, cache: CacheBackend) -> None:
    cache.rpush(announce_key(session_id), str(approval_id))
    cache.expire(announce_key(session_id), ANNOUNCE_TTL_S)


def cache_session_grant_actions(
    *,
    session_id: UUID,
    external_app_id: int,
    action_types: Iterable[str],
    source_approval_id: UUID,
    cache: CacheBackend,
) -> None:
    """Cache the same app/action types for this BuildSession.

    One key per action keeps matching simple and conservative: a future
    multi-action request is auto-approved only when every ASK action it invokes
    has an active key.
    """
    for action_type in set(action_types):
        cache.set(
            _session_grant_key(session_id, external_app_id, action_type),
            str(source_approval_id),
            ex=SESSION_GRANT_TTL_S,
        )


def cached_session_grants_cover(
    *,
    session_id: UUID,
    external_app_id: int,
    action_types: Iterable[str],
    cache: CacheBackend,
) -> bool:
    """Return true iff every action type has an active cached session grant.

    The TTL is sliding while the grant is used. On miss, callers should consult
    the durable DB grant source and rehydrate this cache when covered.
    """
    unique_action_types = set(action_types)
    if not unique_action_types:
        return False
    keys = [
        _session_grant_key(session_id, external_app_id, action_type)
        for action_type in unique_action_types
    ]
    for key in keys:
        if cache.get(key) is None:
            return False
    for key in keys:
        cache.expire(key, SESSION_GRANT_TTL_S)
    return True


async def wait_for_wake(
    approval_id: UUID, timeout_s: int, cache: CacheBackend
) -> ApprovalDecision | None:
    """Block for a decision. `None` on timeout/unparseable payload (caller re-reads the row)."""
    if timeout_s <= 0:
        return None

    deadline = time.monotonic() + timeout_s
    while True:
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            return None

        # `asyncio.to_thread` cannot cancel an in-flight BLPOP, so keep each
        # blocking call short even when the overall wait is configured higher.
        result = await asyncio.to_thread(cache.blpop, [_wake_key(approval_id)], 1)
        if result is None:
            continue

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
    """Wake the parked proxy. A miss just means it waits out the wait timeout."""
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
