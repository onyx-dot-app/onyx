"""Durable harness state of a Firecracker sandbox, in the tenant cache.

- Exec sessions (no TTL): one JSON map per sandbox, exec session ID → the VM
  instance, the guest execution ID, the read offsets and the last use. Any
  API pod can serve `write_stdin` from it.
- Activity marks (each expires): the turns in progress and the parked
  approvals of the sandbox. The idle stop reads them.

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
)

EXEC_SESSIONS_PREFIX = "sandbox_fc:exec_sessions:"
ACTIVITY_PREFIX = "sandbox_fc:harness_activity:"
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


def has_marks(cache: CacheBackend, sandbox_id: UUID) -> bool:
    activity = _read(cache, ACTIVITY_PREFIX + str(sandbox_id), HarnessActivity)
    now = time.time()
    return any(exp > now for exp in activity.marks.values())
