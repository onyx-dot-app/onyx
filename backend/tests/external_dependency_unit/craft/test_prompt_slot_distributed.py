"""Prompt-slot serialization for build sessions, against a real cache (Redis).

The slot is a distributed lock, so these run against a real cache rather than
a stub: two manager instances stand in for two ``api_server`` replicas sharing
one cache, proving cross-pod serialization an in-process test can't.
"""

from __future__ import annotations

import contextlib
import threading
import time
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from onyx.cache import factory
from onyx.cache.interface import CacheBackendType
from onyx.server.features.build.sandbox import serve_transport
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)


def _make_replica() -> KubernetesSandboxManager:
    """A fresh manager (its own state, like a separate pod); skips
    ``_initialize`` so no kube config is needed."""
    m: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    m._init_serve_state()
    return m


@pytest.fixture
def slot_env(
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant context + the Redis backend forced on, so the cross-replica
    lock is real. Short acquire timeouts are passed per call site —
    ``PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS`` binds at import, so patching it
    here would be a no-op."""
    monkeypatch.setattr(factory, "CACHE_BACKEND", CacheBackendType.REDIS)


def test_second_replica_refused_then_admitted_after_release(
    slot_env: None,  # noqa: ARG001
) -> None:
    sandbox_id = uuid4()
    build_session_id = uuid4()
    replica_a = _make_replica()
    replica_b = _make_replica()

    # A holds the slot; B shares only the cache, so the distributed lock must
    # refuse it. Nested `with` keeps A held while B contends.
    with replica_a.prompt_slot(sandbox_id, build_session_id) as first:
        assert first.acquired is True
        with replica_b.prompt_slot(
            sandbox_id, build_session_id, acquire_timeout=1.0
        ) as second:
            assert second.acquired is False

    # A released → a queued third turn can now proceed.
    with replica_b.prompt_slot(sandbox_id, build_session_id) as third:
        assert third.acquired is True


def test_distinct_build_sessions_do_not_block(slot_env: None) -> None:  # noqa: ARG001
    sandbox_id = uuid4()
    mgr = _make_replica()
    with mgr.prompt_slot(sandbox_id, uuid4()) as first:
        assert first.acquired is True
        with mgr.prompt_slot(sandbox_id, uuid4()) as second:
            assert second.acquired is True


def test_slot_released_on_exception(slot_env: None) -> None:  # noqa: ARG001
    sandbox_id = uuid4()
    build_session_id = uuid4()
    mgr = _make_replica()

    with pytest.raises(RuntimeError, match="boom"):
        with mgr.prompt_slot(sandbox_id, build_session_id) as acquired:
            assert acquired.acquired is True
            raise RuntimeError("boom")

    with mgr.prompt_slot(sandbox_id, build_session_id) as after:
        assert after.acquired is True


def test_fails_open_when_cache_unavailable(
    slot_env: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> None:
        raise RedisError("cache down")

    monkeypatch.setattr(serve_transport, "get_cache_backend", _boom)
    with _make_replica().prompt_slot(uuid4(), uuid4()) as acquired:
        assert acquired.acquired is True


@pytest.mark.usefixtures("slot_env")
def test_orphaned_lease_expires_and_is_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve_transport, "PROMPT_SLOT_LEASE_SECONDS", 1.5)
    sandbox_id = uuid4()
    build_session_id = uuid4()
    replica_a = _make_replica()
    replica_b = _make_replica()

    orphan_cm = replica_a.prompt_slot(sandbox_id, build_session_id)
    orphan_slot = orphan_cm.__enter__()
    assert orphan_slot.acquired is True
    # Dead runner: never __exit__, so the lock must expire via the lease TTL.

    try:
        with replica_b.prompt_slot(
            sandbox_id, build_session_id, acquire_timeout=6.0
        ) as second:
            assert second.acquired is True
    finally:
        with contextlib.suppress(Exception):
            orphan_cm.__exit__(None, None, None)


@pytest.mark.usefixtures("slot_env")
def test_live_holder_extends_lease_and_keeps_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve_transport, "PROMPT_SLOT_LEASE_SECONDS", 3.0)
    sandbox_id = uuid4()
    build_session_id = uuid4()
    replica_a = _make_replica()
    replica_b = _make_replica()

    holder_cm = replica_a.prompt_slot(sandbox_id, build_session_id)
    holder_slot = holder_cm.__enter__()
    assert holder_slot.acquired is True

    try:
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            holder_slot.extend()
            time.sleep(0.5)

        # Past the original 3.0s lease — refusal proves extend() renewed it.
        with replica_b.prompt_slot(
            sandbox_id, build_session_id, acquire_timeout=0.2
        ) as competitor:
            assert competitor.acquired is False
    finally:
        holder_cm.__exit__(None, None, None)

    with replica_b.prompt_slot(sandbox_id, build_session_id) as after_release:
        assert after_release.acquired is True


@pytest.mark.usefixtures("slot_env")
def test_lost_lease_detected_on_extend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve_transport, "PROMPT_SLOT_LEASE_SECONDS", 1.0)
    sandbox_id = uuid4()
    build_session_id = uuid4()
    replica_a = _make_replica()
    replica_b = _make_replica()

    holder_cm = replica_a.prompt_slot(sandbox_id, build_session_id)
    slot_a = holder_cm.__enter__()
    assert slot_a.acquired is True

    try:
        # Let the 1.0s lease expire without renewing it.
        time.sleep(1.5)

        with replica_b.prompt_slot(
            sandbox_id, build_session_id, acquire_timeout=2.0
        ) as slot_b:
            assert slot_b.acquired is True

            slot_a.extend()
            assert slot_a.lost is True
            assert slot_b.lost is False
    finally:
        with contextlib.suppress(Exception):
            holder_cm.__exit__(None, None, None)


@pytest.mark.usefixtures("slot_env")
def test_keep_alive_renews_without_loop_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve_transport, "PROMPT_SLOT_LEASE_SECONDS", 1.5)
    sandbox_id = uuid4()
    build_session_id = uuid4()
    replica_a = _make_replica()
    replica_b = _make_replica()

    holder_cm = replica_a.prompt_slot(sandbox_id, build_session_id)
    slot_a = holder_cm.__enter__()
    assert slot_a.acquired is True

    stop_event = threading.Event()
    keep_alive_thread = threading.Thread(
        target=slot_a.keep_alive,
        args=(stop_event, 30.0),
        daemon=True,
    )
    keep_alive_thread.start()

    try:
        # Past the original 1.5s lease, with no manual extend() from the
        # caller — keep_alive's own wall-clock cadence must renew it.
        time.sleep(2.5)

        with replica_b.prompt_slot(
            sandbox_id, build_session_id, acquire_timeout=0.2
        ) as competitor:
            assert competitor.acquired is False
    finally:
        stop_event.set()
        keep_alive_thread.join(timeout=5.0)
        holder_cm.__exit__(None, None, None)

    with replica_b.prompt_slot(sandbox_id, build_session_id) as after_release:
        assert after_release.acquired is True


@pytest.mark.usefixtures("slot_env")
def test_keep_alive_marks_slot_lost_when_window_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve_transport, "PROMPT_SLOT_LEASE_SECONDS", 0.4)
    sandbox_id = uuid4()
    build_session_id = uuid4()
    replica = _make_replica()

    holder_cm = replica.prompt_slot(sandbox_id, build_session_id)
    holder_slot = holder_cm.__enter__()
    assert holder_slot.acquired is True

    try:
        stop = threading.Event()
        holder_slot.keep_alive(stop, max_seconds=0.05)
        assert holder_slot.lost is True
    finally:
        with contextlib.suppress(Exception):
            holder_cm.__exit__(None, None, None)
