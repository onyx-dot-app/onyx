"""Cache-backed lifecycle state for active interactive Craft turns."""

from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from enum import StrEnum
from uuid import UUID
from uuid import uuid4

from onyx.cache.interface import CacheBackend
from onyx.cache.interface import CacheLock


class InteractiveTurnStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TURN_STATUS_QUEUED = InteractiveTurnStatus.QUEUED
TURN_STATUS_RUNNING = InteractiveTurnStatus.RUNNING
TURN_STATUS_SUCCEEDED = InteractiveTurnStatus.SUCCEEDED
TURN_STATUS_FAILED = InteractiveTurnStatus.FAILED
TURN_STATUS_CANCELLED = InteractiveTurnStatus.CANCELLED

ACTIVE_TURN_STATUSES = frozenset((TURN_STATUS_QUEUED, TURN_STATUS_RUNNING))
ACTIVE_TURN_TTL_SECONDS = 45 * 60
REQUEST_ID_TTL_SECONDS = 60 * 60
TURN_LOCK_LEASE_SECONDS = 60.0
TURN_LOCK_WAIT_SECONDS = 10.0
RUNNER_STALE_AFTER_SECONDS = 90.0


class InteractiveTurnLockError(Exception):
    """Raised when the session active-turn lock cannot be acquired."""


@dataclass
class InteractiveTurn:
    turn_id: UUID
    session_id: UUID
    user_id: UUID
    prompt: str
    status: InteractiveTurnStatus
    turn_index: int
    last_heartbeat_at: datetime | None = None
    error_detail: str | None = None
    runner_id: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_TURN_STATUSES


def acquire_active_turn_lock(cache: CacheBackend, session_id: UUID) -> CacheLock:
    lock = cache.lock(
        _active_turn_lock_key(session_id), timeout=TURN_LOCK_LEASE_SECONDS
    )
    if not lock.acquire(blocking=True, blocking_timeout=TURN_LOCK_WAIT_SECONDS):
        raise InteractiveTurnLockError("Failed to acquire active turn lock")
    return lock


def create_interactive_turn(
    *,
    cache: CacheBackend,
    session_id: UUID,
    user_id: UUID,
    client_request_id: str,
    prompt: str,
    turn_index: int,
) -> InteractiveTurn:
    now = datetime.now(tz=timezone.utc)
    turn = InteractiveTurn(
        turn_id=uuid4(),
        session_id=session_id,
        user_id=user_id,
        prompt=prompt,
        status=TURN_STATUS_QUEUED,
        turn_index=turn_index,
        last_heartbeat_at=now,
    )
    _save_turn(cache, turn, ex=ACTIVE_TURN_TTL_SECONDS)
    cache.set(
        _active_turn_key(session_id), str(turn.turn_id), ex=ACTIVE_TURN_TTL_SECONDS
    )
    cache.set(
        _request_key(session_id, user_id, client_request_id),
        str(turn.turn_id),
        ex=REQUEST_ID_TTL_SECONDS,
    )
    return turn


def get_turn(cache: CacheBackend, turn_id: UUID) -> InteractiveTurn | None:
    return _load_turn(cache.get(_turn_key(turn_id)))


def get_turn_for_request(
    *,
    cache: CacheBackend,
    session_id: UUID,
    user_id: UUID,
    client_request_id: str,
) -> InteractiveTurn | None:
    raw_turn_id = cache.get(_request_key(session_id, user_id, client_request_id))
    if raw_turn_id is None:
        return None
    try:
        turn_id = UUID(_decode(raw_turn_id))
    except ValueError:
        return None
    turn = get_turn(cache, turn_id)
    if turn is None or turn.session_id != session_id or turn.user_id != user_id:
        return None
    return turn


def get_active_turn(
    *,
    cache: CacheBackend,
    session_id: UUID,
    user_id: UUID,
) -> InteractiveTurn | None:
    raw_turn_id = cache.get(_active_turn_key(session_id))
    if raw_turn_id is None:
        return None
    try:
        turn_id = UUID(_decode(raw_turn_id))
    except ValueError:
        cache.delete(_active_turn_key(session_id))
        return None
    turn = get_turn(cache, turn_id)
    if turn is None or turn.session_id != session_id or turn.user_id != user_id:
        cache.delete(_active_turn_key(session_id))
        return None
    if not turn.is_active:
        cache.delete(_active_turn_key(session_id))
        return None
    return turn


def claim_turn_for_runner(
    *,
    cache: CacheBackend,
    turn_id: UUID,
    stale_after_seconds: float = RUNNER_STALE_AFTER_SECONDS,
) -> InteractiveTurn | None:
    """Atomically claim a queued or stale-running turn for one runner.

    The claim lives in CacheBackend, not process memory, so another API pod can
    detect and recover a turn whose original runner stopped heartbeating.
    """
    turn = get_turn(cache, turn_id)
    if turn is None or turn.status not in ACTIVE_TURN_STATUSES:
        return None

    try:
        lock = acquire_active_turn_lock(cache, turn.session_id)
    except InteractiveTurnLockError:
        return None

    try:
        turn = get_turn(cache, turn_id)
        if turn is None or turn.status not in ACTIVE_TURN_STATUSES:
            return None
        if turn.status == TURN_STATUS_RUNNING and not _runner_is_stale(
            turn, stale_after_seconds=stale_after_seconds
        ):
            return None

        now = datetime.now(tz=timezone.utc)
        turn.status = TURN_STATUS_RUNNING
        turn.last_heartbeat_at = now
        turn.runner_id = str(uuid4())
        turn.error_detail = None
        _save_turn(cache, turn, ex=ACTIVE_TURN_TTL_SECONDS)
        cache.set(
            _active_turn_key(turn.session_id),
            str(turn.turn_id),
            ex=ACTIVE_TURN_TTL_SECONDS,
        )
        return turn
    finally:
        lock.release()


def touch_turn(
    *,
    cache: CacheBackend,
    turn_id: UUID,
    runner_id: str | None = None,
) -> bool:
    turn = get_turn(cache, turn_id)
    if turn is None or not turn.is_active:
        return False

    try:
        lock = acquire_active_turn_lock(cache, turn.session_id)
    except InteractiveTurnLockError:
        return False

    try:
        turn = get_turn(cache, turn_id)
        if turn is None or not turn.is_active:
            return False
        if runner_id is not None and turn.runner_id != runner_id:
            return False
        turn.last_heartbeat_at = datetime.now(tz=timezone.utc)
        _save_turn(cache, turn, ex=ACTIVE_TURN_TTL_SECONDS)
        cache.expire(_active_turn_key(turn.session_id), ACTIVE_TURN_TTL_SECONDS)
        return True
    finally:
        lock.release()


def finish_turn(
    *,
    cache: CacheBackend,
    turn_id: UUID,
    status: InteractiveTurnStatus,
    error_detail: str | None = None,
    runner_id: str | None = None,
) -> InteractiveTurn | None:
    turn = get_turn(cache, turn_id)
    if turn is None:
        return None

    try:
        lock = acquire_active_turn_lock(cache, turn.session_id)
    except InteractiveTurnLockError:
        return None

    try:
        turn = get_turn(cache, turn_id)
        if turn is None:
            return None
        if runner_id is not None and turn.runner_id != runner_id:
            return None
        now = datetime.now(tz=timezone.utc)
        turn.status = status
        turn.last_heartbeat_at = now
        turn.error_detail = error_detail
        turn.runner_id = None
        _save_turn(cache, turn, ex=REQUEST_ID_TTL_SECONDS)

        raw_active_id = cache.get(_active_turn_key(turn.session_id))
        if raw_active_id is not None and _decode(raw_active_id) == str(turn_id):
            cache.delete(_active_turn_key(turn.session_id))
        return turn
    finally:
        lock.release()


def _runner_is_stale(
    turn: InteractiveTurn,
    *,
    stale_after_seconds: float,
) -> bool:
    if turn.last_heartbeat_at is None:
        return True
    heartbeat = turn.last_heartbeat_at
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    age = datetime.now(tz=timezone.utc) - heartbeat
    return age.total_seconds() >= stale_after_seconds


def _save_turn(cache: CacheBackend, turn: InteractiveTurn, *, ex: int) -> None:
    payload = asdict(turn)
    for field in ("turn_id", "session_id", "user_id"):
        payload[field] = str(payload[field])
    for field in ("last_heartbeat_at",):
        value = payload[field]
        payload[field] = value.isoformat() if value is not None else None
    cache.set(_turn_key(turn.turn_id), json.dumps(payload), ex=ex)


def _load_turn(raw: bytes | None) -> InteractiveTurn | None:
    if raw is None:
        return None
    try:
        payload = json.loads(_decode(raw))
        return InteractiveTurn(
            turn_id=UUID(payload["turn_id"]),
            session_id=UUID(payload["session_id"]),
            user_id=UUID(payload["user_id"]),
            prompt=payload["prompt"],
            status=InteractiveTurnStatus(payload["status"]),
            turn_index=int(payload["turn_index"]),
            last_heartbeat_at=_parse_dt(payload.get("last_heartbeat_at")),
            error_detail=payload.get("error_detail"),
            runner_id=payload.get("runner_id"),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _decode(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _turn_key(turn_id: UUID) -> str:
    return f"craft:interactive_turn:{turn_id}"


def _active_turn_key(session_id: UUID) -> str:
    return f"craft:session:{session_id}:active_turn"


def _active_turn_lock_key(session_id: UUID) -> str:
    return f"craft:session:{session_id}:active_turn_lock"


def _request_key(session_id: UUID, user_id: UUID, client_request_id: str) -> str:
    return f"craft:session:{session_id}:turn_request:{user_id}:{client_request_id}"
