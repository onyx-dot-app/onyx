"""Ephemeral cache signals for the approval rendezvous.

The Postgres `action_approval` row is the source of truth; everything
here is best-effort over `CacheBackend`. Two lists:

* `approval:announce:{session_id}` — proxy RPUSHes after committing the
  row; the chat-stream merger BLPOPs to emit the card on the live SSE
  stream. A miss degrades to the FE's next `/live` refetch.
* `approval:wake:{approval_id}` — api-server RPUSHes when a decision is
  recorded; the parked proxy BLPOPs to wake before the wait timeout.

A command that a chat runs in its VM uses the announce list under its command
ID, and two more keys:

* `approval:command:{command_id}:foreground` — the chat session of a command
  that a call of the chat's run waits on. The call sets and renews it; the
  proxy holds an Ask request of the command only while it is set.
* `approval:command:{command_id}:grant:{chat_session_id}:{integration_id}:{action}`
  — one key per action that the user of the chat approved for the rest of the
  command. Plain keys,
  not a set, so the TTL applies on every cache backend. The harness drops
  them when it sees the command end (`drop_command_grants`).
* `approval:command:{command_id}:granted` — set before the first grant of the
  command, so the drop scans for grant keys only when the command has one.
* `approval:command:{command_id}:ended` — set by `drop_command_grants` before
  it drops the grants. A grant saved after the drop sees it and removes
  itself, so a late save cannot restore a grant of an ended command.
"""

import asyncio
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from onyx.cache.interface import CACHE_TRANSIENT_ERRORS, CacheBackend
from onyx.db.enums import ApprovalDecision, IntegrationKind
from onyx.external_apps.matching.engine import ActionLike, actions_requiring_approval
from onyx.integrations.policy import always_asks
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.db.models import ActionApproval

logger = setup_logger()

# Only need to outlive the gap between RPUSH and the consumer's BLPOP.
ANNOUNCE_TTL_S = 60
WAKE_TTL_S = 30

# Session grant cache keys are an acceleration layer. The durable grant source is
# the action_approval row whose decision was recorded via SESSION_GRANT.
SESSION_GRANT_TTL_S = 60 * 60

# The call that waits on a command renews the key each second; a lost API
# process leaves it for this long.
COMMAND_FOREGROUND_TTL_S = 60
# Only for a command end that nobody reads: the harness drops the grants of a
# command when it sees the command end. The TTL matches the VM's command
# deadline, so a grant covers the command while it runs.
COMMAND_GRANT_TTL_S = 4 * 60 * 60


def announce_key(session_id: UUID) -> str:
    return f"approval:announce:{session_id}"


def _wake_key(approval_id: UUID) -> str:
    return f"approval:wake:{approval_id}"


def _session_grant_key(session_id: UUID, integration_id: int, action_type: str) -> str:
    return f"approval:session-grant:{session_id}:integration:{integration_id}:{action_type}"


def announce_approval(approval_id: UUID, session_id: UUID, cache: CacheBackend) -> None:
    cache.rpush(announce_key(session_id), str(approval_id))
    cache.expire(announce_key(session_id), ANNOUNCE_TTL_S)


def cache_session_grant_actions(
    *,
    session_id: UUID,
    integration_id: int,
    action_types: Iterable[str],
    source_approval_id: UUID,
    cache: CacheBackend,
) -> None:
    """Cache the same integration/action types for this BuildSession.

    One key per action keeps matching simple and conservative: a future
    multi-action request is auto-approved only when every ASK action it invokes
    has an active key.
    """
    for action_type in set(action_types):
        cache.set(
            _session_grant_key(session_id, integration_id, action_type),
            str(source_approval_id),
            ex=SESSION_GRANT_TTL_S,
        )


def hydrate_session_grants(
    *,
    session_id: UUID,
    integration_id: int,
    rows: Iterable["ActionApproval"],
    cache: CacheBackend | None,
) -> set[str]:
    """Union of ASK action types across persisted grant ``rows``, hydrating each
    row's per-action grant keys as a side effect.

    Hydration is best-effort: skipped when ``cache`` is ``None`` and
    warned-and-continued on transient cache errors, so callers always get the
    union back.
    """
    granted: set[str] = set()
    per_row: list[tuple[UUID, list[str]]] = []
    for row in rows:
        action_types = actions_requiring_approval(row.actions)
        granted.update(action_types)
        per_row.append((row.approval_id, action_types))
    if cache is not None:
        try:
            for source_approval_id, action_types in per_row:
                cache_session_grant_actions(
                    session_id=session_id,
                    integration_id=integration_id,
                    action_types=action_types,
                    source_approval_id=source_approval_id,
                    cache=cache,
                )
        except CACHE_TRANSIENT_ERRORS as e:
            logger.warning(
                "approval.session_grant_cache_hydrate_failed session_id=%s "
                "integration=%s error=%s",
                session_id,
                integration_id,
                str(e),
            )
    return granted


def cached_session_grants_cover(
    *,
    session_id: UUID,
    integration_id: int,
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
        _session_grant_key(session_id, integration_id, action_type)
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


def send_wakes(
    approval_ids: Iterable[UUID], decision: ApprovalDecision, cache: CacheBackend
) -> None:
    """Wake each parked proxy. A failed wake leaves only that proxy to its
    wait timeout."""
    for approval_id in approval_ids:
        try:
            send_wake(approval_id, decision, cache)
        except CACHE_TRANSIENT_ERRORS as error:
            logger.warning(
                "approval_wake_failed approval_id=%s error=%r", approval_id, error
            )


def _command_foreground_key(command_id: UUID) -> str:
    return f"approval:command:{command_id}:foreground"


def _command_grant_prefix(command_id: UUID) -> str:
    return f"approval:command:{command_id}:grant:"


def _command_ended_key(command_id: UUID) -> str:
    return f"approval:command:{command_id}:ended"


def _command_granted_key(command_id: UUID) -> str:
    return f"approval:command:{command_id}:granted"


def _command_grant_key(
    command_id: UUID, chat_session_id: UUID, integration_id: int, action_type: str
) -> str:
    return (
        f"{_command_grant_prefix(command_id)}"
        f"{chat_session_id}:{integration_id}:{action_type}"
    )


def mark_command_foreground(
    command_id: UUID, chat_session_id: UUID, cache: CacheBackend
) -> None:
    """Set or renew the mark of a command that a call waits on."""
    cache.set(
        _command_foreground_key(command_id),
        str(chat_session_id),
        ex=COMMAND_FOREGROUND_TTL_S,
    )


def clear_command_foreground(command_id: UUID, cache: CacheBackend) -> None:
    cache.delete(_command_foreground_key(command_id))


def command_in_foreground(
    command_id: UUID, chat_session_id: UUID, cache: CacheBackend
) -> bool:
    """Whether a call of `chat_session_id` waits on the command now."""
    value = cache.get(_command_foreground_key(command_id))
    return value is not None and value.decode() == str(chat_session_id)


def command_grant_actions(actions: Iterable[ActionLike]) -> list[str]:
    """The action types that approving a request for the rest of its command
    covers: its Ask actions. None when one of its actions could always ask:
    the row has no integration kind, so this takes the strict API rule."""
    action_types = actions_requiring_approval(actions)
    if any(always_asks(IntegrationKind.API, t) for t in action_types):
        return []
    return action_types


def grant_command_actions(
    command_id: UUID,
    chat_session_id: UUID,
    integration_id: int,
    action_types: Iterable[str],
    cache: CacheBackend,
) -> None:
    keys = {
        _command_grant_key(command_id, chat_session_id, integration_id, action_type)
        for action_type in action_types
    }
    cache.set(_command_granted_key(command_id), b"1", ex=COMMAND_GRANT_TTL_S)
    for key in keys:
        cache.set(key, b"1", ex=COMMAND_GRANT_TTL_S)
    # Write, then check: either the drop sees these grants or this sees its
    # mark (`drop_command_grants`).
    if cache.exists(_command_ended_key(command_id)):
        for key in keys:
            cache.delete(key)


def command_grants_cover(
    command_id: UUID,
    chat_session_id: UUID,
    integration_id: int,
    action_types: Iterable[str],
    cache: CacheBackend,
) -> bool:
    """Whether the user of the chat approved every one of `action_types`
    (non-empty) for the rest of the command."""
    keys = {
        _command_grant_key(command_id, chat_session_id, integration_id, action_type)
        for action_type in action_types
    }
    return bool(keys) and cache.exists_many(keys) == keys


def drop_command_grants(command_id: UUID, cache: CacheBackend) -> None:
    """The command ended: a process that it left running gets no grant.
    The mark comes first, so a grant saved during the drop removes itself.
    A command without a grant skips the scan of its grant keys."""
    cache.set(_command_ended_key(command_id), b"1", ex=COMMAND_GRANT_TTL_S)
    if cache.exists(_command_granted_key(command_id)):
        cache.delete_prefix(_command_grant_prefix(command_id))


def end_announcement_wait(session_id: UUID, cache: CacheBackend) -> None:
    """Return a `pop_announcement` that waits now, or the next one, at once."""
    cache.rpush(announce_key(session_id), "end")
    cache.expire(announce_key(session_id), ANNOUNCE_TTL_S)


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
