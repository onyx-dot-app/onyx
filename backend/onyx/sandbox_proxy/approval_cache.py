"""Ephemeral Redis state for the approval rendezvous between the
egress proxy and the api-server.

The Postgres ``action_approval`` row is the source of truth — its
conditional ``WHERE decision IS NULL`` UPDATE is the only arbiter of
who wins a terminal write. Functions here are best-effort cache ops
that drive UI freshness and unblock the proxy's wait; callers must
swallow ``CACHE_TRANSIENT_ERRORS`` where appropriate.

Two Redis keys back the rendezvous:

* ``approval:live:{id}`` — a short-TTL presence flag the proxy owns
  while it's parked on a decision. The chat shows an actionable card
  iff this key exists AND the DB row is undecided. A hard proxy
  crash lets the key lapse within ``LIVENESS_TTL_S`` and the card
  disappears on its own.

* ``approval:wake:{id}`` — a one-shot BLPOP list the api-server
  pushes onto when a decision is recorded, so the proxy's wait
  unblocks immediately rather than timing out 180s later.
"""

import asyncio
from uuid import UUID

from onyx.cache.interface import CacheBackend
from onyx.db.enums import ApprovalDecision

# Heartbeat is the cadence at which the proxy refreshes the liveness
# key; the TTL is set to 4× the heartbeat so two missed refreshes
# (network blip, GC pause) still leave the key alive.
HEARTBEAT_INTERVAL_S = 15
LIVENESS_TTL_S = HEARTBEAT_INTERVAL_S * 4  # 60s
# Wake TTL just needs to outlive the gap between the API's RPUSH and
# the proxy's BLPOP. If no one consumes it, the key auto-evicts.
WAKE_TTL_S = 30


def _live_key(approval_id: UUID) -> str:
    return f"approval:live:{approval_id}"


def _wake_key(approval_id: UUID) -> str:
    return f"approval:wake:{approval_id}"


# ---------------------------------------------------------------------------
# Proxy side — writes the liveness flag, waits on the wake channel.
# ---------------------------------------------------------------------------


def set_alive(approval_id: UUID, proxy_instance_id: str, cache: CacheBackend) -> None:
    """Refresh (or initially publish) the proxy's liveness flag.

    Idempotent — used both for the initial set and each heartbeat tick.
    """
    cache.set(_live_key(approval_id), proxy_instance_id, ex=LIVENESS_TTL_S)


def clear_alive(approval_id: UUID, cache: CacheBackend) -> None:
    cache.delete(_live_key(approval_id))


async def wait_for_wake(
    approval_id: UUID, timeout_s: int, cache: CacheBackend
) -> ApprovalDecision | None:
    """Block until the api-server pushes a decision, or timeout.

    Wraps the blocking BLPOP in ``asyncio.to_thread`` so the proxy's
    event loop stays free. Returns the decoded ``ApprovalDecision`` or
    ``None`` on timeout / unparseable payload (caller treats both the
    same way: re-read the row from Postgres).
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
        # Junk on the wake channel — stale key from a previous schema,
        # or a manual RPUSH. Fall through to the read-back path so the
        # gate doesn't crash.
        return None


# ---------------------------------------------------------------------------
# API side — reads the liveness flag, signals decisions onto the wake channel.
# ---------------------------------------------------------------------------


def is_alive(approval_id: UUID, cache: CacheBackend) -> bool:
    return cache.exists(_live_key(approval_id))


def send_wake(
    approval_id: UUID, decision: ApprovalDecision, cache: CacheBackend
) -> None:
    """Push a decision onto the wake channel for the parked proxy.

    Best-effort: a missed wake just means the proxy waits out its
    timeout and reads the winning decision from Postgres. RPUSH +
    EXPIRE so a never-consumed wake auto-evicts.
    """
    cache.rpush(_wake_key(approval_id), decision.value)
    cache.expire(_wake_key(approval_id), WAKE_TTL_S)


def finalize(
    approval_id: UUID, decision: ApprovalDecision, cache: CacheBackend
) -> None:
    """End-of-life cache cleanup after a terminal decision is recorded.

    Clears the liveness flag (so the chat hides the card) and pushes
    the decision onto the wake channel (so the proxy unblocks).
    Cleared first so a racing ``is_alive`` check sees the terminal
    state immediately.
    """
    clear_alive(approval_id, cache)
    send_wake(approval_id, decision, cache)
