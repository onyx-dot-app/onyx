"""Prompt-slot serialization for build sessions, against a real cache (Redis).

The slot is a distributed lock, so these run against a real cache rather than
a stub: two manager instances stand in for two ``api_server`` replicas sharing
one cache, proving cross-pod serialization an in-process test can't.
"""

from __future__ import annotations

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
    """Tenant context + a short acquire timeout + the Redis backend forced on,
    so the contended path returns quickly and the cross-replica lock is real."""
    monkeypatch.setattr(serve_transport, "PROMPT_SLOT_ACQUIRE_TIMEOUT_SECONDS", 1.0)
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
        assert first is True
        with replica_b.prompt_slot(sandbox_id, build_session_id) as second:
            assert second is False

    # A released → a queued third turn can now proceed.
    with replica_b.prompt_slot(sandbox_id, build_session_id) as third:
        assert third is True


def test_distinct_build_sessions_do_not_block(slot_env: None) -> None:  # noqa: ARG001
    sandbox_id = uuid4()
    mgr = _make_replica()
    with mgr.prompt_slot(sandbox_id, uuid4()) as first:
        assert first is True
        with mgr.prompt_slot(sandbox_id, uuid4()) as second:
            assert second is True


def test_slot_released_on_exception(slot_env: None) -> None:  # noqa: ARG001
    sandbox_id = uuid4()
    build_session_id = uuid4()
    mgr = _make_replica()

    with pytest.raises(RuntimeError, match="boom"):
        with mgr.prompt_slot(sandbox_id, build_session_id) as acquired:
            assert acquired is True
            raise RuntimeError("boom")

    with mgr.prompt_slot(sandbox_id, build_session_id) as after:
        assert after is True


def test_fails_open_when_cache_unavailable(
    slot_env: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> None:
        raise RedisError("cache down")

    monkeypatch.setattr(serve_transport, "get_cache_backend", _boom)
    with _make_replica().prompt_slot(uuid4(), uuid4()) as acquired:
        assert acquired is True
