"""Durable harness state of a Firecracker sandbox, in the tenant cache.

- Exec sessions (NO TTL): one JSON map per sandbox, exec session ID → the VM
  instance (attempt, generation), the guest execution ID, the read offsets
  and the last use. Any API pod can serve `write_stdin` from it. A record of
  another VM instance is dead (the processes did not survive): the caller
  reports "session ended" and the next write drops it.
- Activity (entries expire): per sandbox, the chat sessions with a turn in
  progress or a parked approval. The idle stop reads it.

Writes are compare-and-set on the stored value, as the placement record in
`onyx.microvm.registry`. Keys without a TTL need a Redis eviction policy that
never evicts them (see `onyx.microvm.registry`).
"""

import time
from collections.abc import Callable
from enum import Enum
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from onyx.cache.interface import CacheBackend

_EXEC_SESSIONS_PREFIX = "sandbox_fc:exec_sessions:"
_ACTIVITY_PREFIX = "sandbox_fc:harness_activity:"
_CAS_TRIES = 16

_T = TypeVar("_T")
_M = TypeVar("_M", bound=BaseModel)


class ExecSessionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    exec_session_id: str
    chat_session_id: str
    execution_id: str
    attempt: int
    generation: int
    stdout_offset: int = 0
    stderr_offset: int = 0
    last_used: float

    def on_instance(self, attempt: int, generation: int) -> bool:
        return (self.attempt, self.generation) == (attempt, generation)


class _ExecSessions(BaseModel):
    sessions: dict[str, ExecSessionRecord] = {}


class _Activity(BaseModel):
    # chat session ID → Unix seconds when the mark expires.
    turns: dict[str, float] = {}
    approvals: dict[str, float] = {}


class ActivityKind(str, Enum):
    TURN = "turn"
    APPROVAL = "approval"


class StateContentionError(Exception):
    """Too many concurrent writers for one sandbox record."""


def _update(
    cache: CacheBackend,
    key: str,
    parse: Callable[[bytes | None], _M],
    change: Callable[[_M], tuple[_M | None, _T]],
) -> _T:
    """Read, change and compare-and-set one JSON record. `change` returns
    the new record (None: delete it) and the result to return."""
    for _ in range(_CAS_TRIES):
        raw = cache.get(key)
        new, result = change(parse(raw))
        if new is None:
            if raw is None or cache.delete_if_value(key, raw):
                return result
            continue
        payload = new.model_dump_json()
        if raw is None:
            if cache.set_if_absent(key, payload):
                return result
        elif payload.encode() == raw or cache.replace_if_value(key, raw, payload):
            return result
    raise StateContentionError(key)


def _parse_sessions(raw: bytes | None) -> _ExecSessions:
    return _ExecSessions() if raw is None else _ExecSessions.model_validate_json(raw)


def _sessions_key(sandbox_id: UUID) -> str:
    return _EXEC_SESSIONS_PREFIX + str(sandbox_id)


def _eviction_order(
    sessions: dict[str, ExecSessionRecord], ended_execution_ids: set[str]
) -> list[str]:
    """Ended commands first, then running ones; least recently used first."""
    return sorted(
        sessions,
        key=lambda s: (
            sessions[s].execution_id not in ended_execution_ids,
            sessions[s].last_used,
        ),
    )


def add_exec_session(
    cache: CacheBackend,
    sandbox_id: UUID,
    record: ExecSessionRecord,
    *,
    max_sessions: int,
    ended_execution_ids: set[str],
) -> list[ExecSessionRecord] | None:
    """Store a new exec session. Drops the records of older VM instances,
    then evicts down to `max_sessions`. Returns the evicted records (their
    commands may still run), or None when a newer VM instance already has
    records: the record's VM is gone, and nothing is stored."""
    fence = (record.attempt, record.generation)

    def change(
        state: _ExecSessions,
    ) -> tuple[_ExecSessions | None, list[ExecSessionRecord] | None]:
        if any((r.attempt, r.generation) > fence for r in state.sessions.values()):
            return state, None
        sessions = {
            sid: r
            for sid, r in state.sessions.items()
            if r.on_instance(record.attempt, record.generation)
        }
        evicted: list[ExecSessionRecord] = []
        for sid in _eviction_order(sessions, ended_execution_ids):
            if len(sessions) < max_sessions:
                break
            evicted.append(sessions.pop(sid))
        sessions[record.exec_session_id] = record
        return _ExecSessions(sessions=sessions), evicted

    return _update(cache, _sessions_key(sandbox_id), _parse_sessions, change)


def get_exec_session(
    cache: CacheBackend, sandbox_id: UUID, exec_session_id: str
) -> ExecSessionRecord | None:
    return _parse_sessions(cache.get(_sessions_key(sandbox_id))).sessions.get(
        exec_session_id
    )


def list_exec_sessions(
    cache: CacheBackend, sandbox_id: UUID
) -> list[ExecSessionRecord]:
    return list(_parse_sessions(cache.get(_sessions_key(sandbox_id))).sessions.values())


def update_exec_session(
    cache: CacheBackend,
    sandbox_id: UUID,
    exec_session_id: str,
    *,
    execution_id: str,
    stdout_offset: int,
    stderr_offset: int,
) -> bool:
    """Advance the offsets and the last use of a session, while the record
    still names `execution_id`. Offsets never move back."""

    def change(state: _ExecSessions) -> tuple[_ExecSessions | None, bool]:
        current = state.sessions.get(exec_session_id)
        if current is None or current.execution_id != execution_id:
            return state, False
        sessions = dict(state.sessions)
        sessions[exec_session_id] = current.model_copy(
            update={
                "stdout_offset": max(current.stdout_offset, stdout_offset),
                "stderr_offset": max(current.stderr_offset, stderr_offset),
                "last_used": max(current.last_used, time.time()),
            }
        )
        return _ExecSessions(sessions=sessions), True

    return _update(cache, _sessions_key(sandbox_id), _parse_sessions, change)


def remove_exec_session(
    cache: CacheBackend, sandbox_id: UUID, exec_session_id: str, *, execution_id: str
) -> bool:
    """Remove a session while the record still names `execution_id`."""

    def change(state: _ExecSessions) -> tuple[_ExecSessions | None, bool]:
        current = state.sessions.get(exec_session_id)
        if current is None or current.execution_id != execution_id:
            return state, False
        sessions = {
            sid: r for sid, r in state.sessions.items() if sid != exec_session_id
        }
        return (_ExecSessions(sessions=sessions) if sessions else None), True

    return _update(cache, _sessions_key(sandbox_id), _parse_sessions, change)


def clear_exec_sessions(cache: CacheBackend, sandbox_id: UUID) -> None:
    cache.delete(_sessions_key(sandbox_id))


def _parse_activity(raw: bytes | None) -> _Activity:
    return _Activity() if raw is None else _Activity.model_validate_json(raw)


def _activity_key(sandbox_id: UUID) -> str:
    return _ACTIVITY_PREFIX + str(sandbox_id)


def _live(marks: dict[str, float], now: float) -> dict[str, float]:
    return {sid: exp for sid, exp in marks.items() if exp > now}


def set_activity_mark(
    cache: CacheBackend,
    sandbox_id: UUID,
    session_id: UUID,
    *,
    kind: ActivityKind,
    ttl_seconds: float | None,
) -> None:
    """Set (ttl_seconds) or clear (None) one chat session's mark."""

    def change(state: _Activity) -> tuple[_Activity | None, None]:
        now = time.time()
        turns = _live(state.turns, now)
        approvals = _live(state.approvals, now)
        marks = turns if kind is ActivityKind.TURN else approvals
        if ttl_seconds is None:
            marks.pop(str(session_id), None)
        else:
            marks[str(session_id)] = now + ttl_seconds
        if not turns and not approvals:
            return None, None
        return _Activity(turns=turns, approvals=approvals), None

    _update(cache, _activity_key(sandbox_id), _parse_activity, change)


def has_activity(cache: CacheBackend, sandbox_id: UUID) -> bool:
    """True while a turn or a parked approval mark is live."""
    raw = cache.get(_activity_key(sandbox_id))
    if raw is None:
        return False
    state = _parse_activity(raw)
    now = time.time()
    return bool(_live(state.turns, now) or _live(state.approvals, now))


def clear_activity(cache: CacheBackend, sandbox_id: UUID) -> None:
    cache.delete(_activity_key(sandbox_id))
