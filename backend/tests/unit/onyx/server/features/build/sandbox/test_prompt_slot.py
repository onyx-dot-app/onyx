"""Unit tests for ``KubernetesSandboxManager.prompt_slot``.

``prompt_slot`` serializes turns per build session via the distributed cache
lock (opencode-serve's ``prompt_async`` is not concurrent-safe). These run
hermetically against an in-memory cache fake and assert the
acquire/refuse/release contract plus fail-open on cache error; the real
cross-replica proof lives in ``test_prompt_slot_distributed.py``.
"""

from __future__ import annotations

import threading
from typing import NoReturn
from uuid import UUID
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from onyx.cache.interface import CacheLock
from onyx.server.features.build.sandbox import serve_transport
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)


class _FakeCacheLock(CacheLock):
    """In-memory ``CacheLock`` backed by a process-local ``threading.Lock``,
    shared by name across backend instances so it serializes like the real one."""

    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock
        self._owned = False

    def acquire(
        self, blocking: bool = True, blocking_timeout: float | None = None
    ) -> bool:
        if not blocking:
            self._owned = self._lock.acquire(blocking=False)
        else:
            self._owned = self._lock.acquire(
                timeout=blocking_timeout if blocking_timeout is not None else -1
            )
        return self._owned

    def release(self) -> None:
        if self._owned:
            self._lock.release()
            self._owned = False

    def owned(self) -> bool:
        return self._owned


class _FakeCacheBackend:
    """Minimal fake exposing only ``lock`` — the one method ``prompt_slot`` uses."""

    def __init__(self, registry: dict[str, threading.Lock]) -> None:
        self._registry = registry

    def lock(
        self,
        name: str,
        timeout: float | None = None,  # noqa: ARG002
    ) -> CacheLock:
        return _FakeCacheLock(self._registry.setdefault(name, threading.Lock()))


@pytest.fixture(autouse=True)
def _fake_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic: swap the real (Redis/Postgres) cache for an in-memory fake so
    unit tests never touch an external service."""
    registry: dict[str, threading.Lock] = {}
    monkeypatch.setattr(
        serve_transport,
        "get_cache_backend",
        lambda: _FakeCacheBackend(registry),
    )


@pytest.fixture(autouse=True)
def _fast_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the contended-acquire wait short so the "refused" tests don't block
    the full default budget."""
    monkeypatch.setattr(serve_transport, "PROMPT_SLOT_ACQUIRE_TIMEOUT_SECONDS", 0.5)


@pytest.fixture
def mgr() -> KubernetesSandboxManager:
    """Manager with just serve-transport state populated; skips
    ``_initialize`` so no kube config is required."""
    m: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    m._init_serve_state()
    return m


_SBX: UUID = uuid4()
_SES: UUID = uuid4()  # build_session_id (the lock key)


def test_prompt_slot_first_call_acquires(mgr: KubernetesSandboxManager) -> None:
    """A fresh lock on a never-seen session must be acquirable."""
    with mgr.prompt_slot(_SBX, _SES) as acquired:
        assert acquired is True


def test_prompt_slot_rejects_second_concurrent_acquire(
    mgr: KubernetesSandboxManager,
) -> None:
    """The load-bearing invariant: while one turn holds the slot,
    a second concurrent acquire MUST return False non-blocking. This is
    what prevents the phantom-user_message bug."""
    with mgr.prompt_slot(_SBX, _SES) as outer:
        assert outer is True
        with mgr.prompt_slot(_SBX, _SES) as inner:
            assert inner is False, (
                "second concurrent acquire on the same session must return False"
            )


def test_prompt_slot_releases_on_exit(mgr: KubernetesSandboxManager) -> None:
    """After the first turn finishes (context exits), the next turn must
    be able to acquire — the lock must be properly released."""
    with mgr.prompt_slot(_SBX, _SES) as first:
        assert first is True
    # First context exited; second acquire should now succeed.
    with mgr.prompt_slot(_SBX, _SES) as second:
        assert second is True


def test_prompt_slot_releases_on_exception(mgr: KubernetesSandboxManager) -> None:
    """If the turn raises, the lock MUST still be released — otherwise a
    single bad turn would permanently block the session."""
    with pytest.raises(RuntimeError, match="simulated"):
        with mgr.prompt_slot(_SBX, _SES) as acquired:
            assert acquired is True
            raise RuntimeError("simulated turn failure")
    # Lock released — next acquire succeeds.
    with mgr.prompt_slot(_SBX, _SES) as after:
        assert after is True


def test_prompt_slot_different_sessions_dont_block(
    mgr: KubernetesSandboxManager,
) -> None:
    """The lock keys on (sandbox_id, build_session_id) — two DIFFERENT
    build sessions on the same sandbox must NOT serialize. Otherwise a
    user with multiple BuildSessions sharing one pod couldn't have two
    in-flight turns simultaneously."""
    other_session: UUID = uuid4()
    with mgr.prompt_slot(_SBX, _SES) as first:
        assert first is True
        with mgr.prompt_slot(_SBX, other_session) as second:
            assert second is True


def test_prompt_slot_different_sandboxes_dont_block(
    mgr: KubernetesSandboxManager,
) -> None:
    """Same build_session_id across two different sandboxes is
    practically impossible (build sessions belong to one user, one
    sandbox) but the lock granularity still keys on the tuple, so
    serializing across sandboxes would be wrong."""
    other_sandbox = uuid4()
    with mgr.prompt_slot(_SBX, _SES) as first:
        assert first is True
        with mgr.prompt_slot(other_sandbox, _SES) as second:
            assert second is True


def test_prompt_slot_fails_open_on_cache_error(
    mgr: KubernetesSandboxManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cache outage must not brick every turn: when the cache raises a
    transient error, the slot fails open (yields True) and the local guard
    still serializes same-pod."""

    def _boom() -> NoReturn:
        raise RedisError("cache down")

    monkeypatch.setattr(serve_transport, "get_cache_backend", _boom)
    with mgr.prompt_slot(_SBX, _SES) as acquired:
        assert acquired is True
