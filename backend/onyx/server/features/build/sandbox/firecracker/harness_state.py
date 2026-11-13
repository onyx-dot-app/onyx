"""Durable harness state of a Firecracker sandbox, in the tenant cache.

- Exec sessions (no TTL): one JSON map per sandbox, exec session ID → the VM
  instance, the guest execution ID, the read offsets and the last use. Any
  API pod can serve `write_stdin` from it.
- Activity marks (each expires): the turns in progress and the parked
  approvals of the sandbox. The idle stop reads them.
- Session instances (no TTL): per sandbox, the chat sessions set up on a VM
  instance. The idle stop saves these sessions.
- Session saves (no TTL): per chat session, the committed archive in the
  file store. A new save is committed before the old file is deleted.
- Last attempt (no TTL): an agent never creates a stopped attempt again.
- Saved sessions and artifacts (no TTL): per sandbox, the chat sessions
  with a committed save and the published artifact file IDs. A purge
  deletes their files.
- Wanted (expires): when a call last asked for the sandbox. A stop that
  saves gives way to it (cancel on resume).
- Purge marks (expire): a deleted session or sandbox. A save in progress
  does not commit for it.

Writes are compare-and-set on the stored value (parallel tool calls write
the same map). Keys without a TTL need a Redis eviction policy that never
evicts them (see `onyx.microvm.registry`).
"""

import time
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from onyx.cache.interface import CacheBackend
from onyx.server.features.build.sandbox import harness_base
from onyx.server.features.build.sandbox.firecracker.models import (
    ExecSessionRecord,
    ExecSessionTable,
    HarnessActivity,
    IdSet,
    SessionInstanceTable,
    SessionSave,
)

EXEC_SESSIONS_PREFIX = "sandbox_fc:exec_sessions:"
ACTIVITY_PREFIX = "sandbox_fc:harness_activity:"
SESSION_INSTANCES_PREFIX = "sandbox_fc:session_instances:"
SESSION_SAVE_PREFIX = "sandbox_fc:session_save:"
LAST_ATTEMPT_PREFIX = "sandbox_fc:last_attempt:"
SAVED_SESSIONS_PREFIX = "sandbox_fc:saved_sessions:"
ARTIFACTS_PREFIX = "sandbox_fc:artifacts:"
WANTED_PREFIX = "sandbox_fc:wanted:"
PURGED_SESSION_PREFIX = "sandbox_fc:purged_session:"
PURGED_SANDBOX_PREFIX = "sandbox_fc:purged_sandbox:"
SESSION_SAVE_LOCK_PREFIX = "sandbox_fc:session_save_lock:"
# Longer than any save in progress (one session takes 35 min at most).
PURGE_MARK_SECONDS = 24 * 3600
WANTED_SECONDS = 600
# Per-sandbox records that a sandbox purge deletes at its end (the
# saved-session and artifact indexes empty as their files go).
SANDBOX_STATE_PREFIXES = (
    EXEC_SESSIONS_PREFIX,
    ACTIVITY_PREFIX,
    SESSION_INSTANCES_PREFIX,
    LAST_ATTEMPT_PREFIX,
    WANTED_PREFIX,
)
_CAS_TRIES = 16

_M = TypeVar("_M", bound=BaseModel)


class StateContentionError(Exception):
    """Too many concurrent writers for one sandbox record."""


def _read(cache: CacheBackend, key: str, model: type[_M]) -> _M:
    raw = cache.get(key)
    return model() if raw is None else model.model_validate_json(raw)


def _update(
    cache: CacheBackend,
    key: str,
    model: type[_M],
    change: Callable[[_M], _M | None],
) -> None:
    """Read, change and compare-and-set one JSON record (None: delete it)."""
    for _ in range(_CAS_TRIES):
        raw = cache.get(key)
        new = change(model() if raw is None else model.model_validate_json(raw))
        if new is None:
            if raw is None or cache.delete_if_value(key, raw):
                return
            continue
        payload = new.model_dump_json()
        if raw is None:
            if cache.set_if_absent(key, payload):
                return
        elif payload.encode() == raw or cache.replace_if_value(key, raw, payload):
            return
    raise StateContentionError(key)


def get_exec_session(
    cache: CacheBackend, sandbox_id: UUID, exec_session_id: str
) -> ExecSessionRecord | None:
    key = EXEC_SESSIONS_PREFIX + str(sandbox_id)
    return _read(cache, key, ExecSessionTable).sessions.get(exec_session_id)


def put_exec_session(
    cache: CacheBackend, sandbox_id: UUID, record: ExecSessionRecord
) -> None:
    """Store or replace a record. Keeps the most recently used ones."""

    def change(table: ExecSessionTable) -> ExecSessionTable:
        sessions = {**table.sessions, record.exec_session_id: record}
        kept = sorted(sessions.values(), key=lambda r: r.last_used)[
            -harness_base.MAX_EXEC_SESSIONS_PER_SANDBOX :
        ]
        return ExecSessionTable(sessions={r.exec_session_id: r for r in kept})

    _update(cache, EXEC_SESSIONS_PREFIX + str(sandbox_id), ExecSessionTable, change)


def remove_exec_session(
    cache: CacheBackend, sandbox_id: UUID, exec_session_id: str
) -> None:
    def change(table: ExecSessionTable) -> ExecSessionTable | None:
        sessions = {
            sid: r for sid, r in table.sessions.items() if sid != exec_session_id
        }
        return ExecSessionTable(sessions=sessions) if sessions else None

    _update(cache, EXEC_SESSIONS_PREFIX + str(sandbox_id), ExecSessionTable, change)


def set_mark(
    cache: CacheBackend, sandbox_id: UUID, name: str, ttl_seconds: float | None
) -> None:
    """Set (ttl_seconds) or clear (None) one activity mark."""

    def change(activity: HarnessActivity) -> HarnessActivity | None:
        now = time.time()
        marks = {n: exp for n, exp in activity.marks.items() if exp > now}
        if ttl_seconds is None:
            marks.pop(name, None)
        else:
            marks[name] = now + ttl_seconds
        return HarnessActivity(marks=marks) if marks else None

    _update(cache, ACTIVITY_PREFIX + str(sandbox_id), HarnessActivity, change)


def has_marks(cache: CacheBackend, sandbox_id: UUID, name: str | None = None) -> bool:
    """An activity mark that has not expired (`name`: only that mark)."""
    activity = _read(cache, ACTIVITY_PREFIX + str(sandbox_id), HarnessActivity)
    now = time.time()
    return any(
        exp > now and (name is None or n == name) for n, exp in activity.marks.items()
    )


def sessions_on_instance(
    cache: CacheBackend, sandbox_id: UUID, instance: tuple[int, int]
) -> list[UUID]:
    key = SESSION_INSTANCES_PREFIX + str(sandbox_id)
    table = _read(cache, key, SessionInstanceTable)
    return [UUID(sid) for sid, i in table.sessions.items() if i == instance]


def mark_session_on_instance(
    cache: CacheBackend, sandbox_id: UUID, session_id: UUID, instance: tuple[int, int]
) -> None:
    """Record a session as set up on `instance`; drop other instances."""

    def change(table: SessionInstanceTable) -> SessionInstanceTable:
        sessions = {sid: i for sid, i in table.sessions.items() if i == instance}
        sessions[str(session_id)] = instance
        return SessionInstanceTable(sessions=sessions)

    _update(
        cache, SESSION_INSTANCES_PREFIX + str(sandbox_id), SessionInstanceTable, change
    )


def forget_session_on_instances(
    cache: CacheBackend, sandbox_id: UUID, session_id: UUID
) -> None:
    def change(table: SessionInstanceTable) -> SessionInstanceTable | None:
        sessions = {
            sid: i for sid, i in table.sessions.items() if sid != str(session_id)
        }
        return SessionInstanceTable(sessions=sessions) if sessions else None

    _update(
        cache, SESSION_INSTANCES_PREFIX + str(sandbox_id), SessionInstanceTable, change
    )


def get_session_save(cache: CacheBackend, session_id: UUID) -> SessionSave | None:
    raw = cache.get(SESSION_SAVE_PREFIX + str(session_id))
    return None if raw is None else SessionSave.model_validate_json(raw)


def set_session_save(cache: CacheBackend, session_id: UUID, save: SessionSave) -> None:
    cache.set(SESSION_SAVE_PREFIX + str(session_id), save.model_dump_json())


def pop_session_save(cache: CacheBackend, session_id: UUID) -> SessionSave | None:
    """Delete the save record and return it (None: there was none)."""
    key = SESSION_SAVE_PREFIX + str(session_id)
    for _ in range(_CAS_TRIES):
        raw = cache.get(key)
        if raw is None:
            return None
        if cache.delete_if_value(key, raw):
            return SessionSave.model_validate_json(raw)
    raise StateContentionError(key)


def delete_session_save_if(
    cache: CacheBackend, session_id: UUID, save: SessionSave
) -> bool:
    """Delete the save record only while it is still `save`."""
    return cache.delete_if_value(
        SESSION_SAVE_PREFIX + str(session_id), save.model_dump_json().encode()
    )


def get_ids(cache: CacheBackend, prefix: str, sandbox_id: UUID) -> list[str]:
    return _read(cache, prefix + str(sandbox_id), IdSet).ids


def add_id(cache: CacheBackend, prefix: str, sandbox_id: UUID, item: str) -> None:
    def change(record: IdSet) -> IdSet:
        return IdSet(ids=sorted({*record.ids, item}))

    _update(cache, prefix + str(sandbox_id), IdSet, change)


def remove_id(cache: CacheBackend, prefix: str, sandbox_id: UUID, item: str) -> None:
    def change(record: IdSet) -> IdSet | None:
        ids = [i for i in record.ids if i != item]
        return IdSet(ids=ids) if ids else None

    _update(cache, prefix + str(sandbox_id), IdSet, change)


def note_wanted(cache: CacheBackend, sandbox_id: UUID) -> None:
    """Record that a call asks for the sandbox now."""
    cache.set(WANTED_PREFIX + str(sandbox_id), str(time.time()), ex=WANTED_SECONDS)


def wanted_since(cache: CacheBackend, sandbox_id: UUID, since: float) -> bool:
    raw = cache.get(WANTED_PREFIX + str(sandbox_id))
    return raw is not None and float(raw) >= since


def mark_purged(
    cache: CacheBackend,
    *,
    sandbox_id: UUID | None = None,
    session_id: UUID | None = None,
) -> None:
    if sandbox_id is not None:
        cache.set(PURGED_SANDBOX_PREFIX + str(sandbox_id), "1", ex=PURGE_MARK_SECONDS)
    if session_id is not None:
        cache.set(PURGED_SESSION_PREFIX + str(session_id), "1", ex=PURGE_MARK_SECONDS)


def is_sandbox_purged(cache: CacheBackend, sandbox_id: UUID) -> bool:
    return cache.get(PURGED_SANDBOX_PREFIX + str(sandbox_id)) is not None


def is_purged(cache: CacheBackend, sandbox_id: UUID, session_id: UUID) -> bool:
    return (
        cache.get(PURGED_SANDBOX_PREFIX + str(sandbox_id)) is not None
        or cache.get(PURGED_SESSION_PREFIX + str(session_id)) is not None
    )


def last_attempt(cache: CacheBackend, sandbox_id: UUID) -> int:
    """The highest VM attempt the sandbox has had (0: none)."""
    raw = cache.get(LAST_ATTEMPT_PREFIX + str(sandbox_id))
    return 0 if raw is None else int(raw)


def record_attempt(cache: CacheBackend, sandbox_id: UUID, attempt: int) -> None:
    """Raise the stored attempt to `attempt`; it never decreases."""
    key = LAST_ATTEMPT_PREFIX + str(sandbox_id)
    for _ in range(_CAS_TRIES):
        raw = cache.get(key)
        if raw is None:
            if cache.set_if_absent(key, str(attempt)):
                return
        elif int(raw) >= attempt or cache.replace_if_value(key, raw, str(attempt)):
            return
    raise StateContentionError(key)
