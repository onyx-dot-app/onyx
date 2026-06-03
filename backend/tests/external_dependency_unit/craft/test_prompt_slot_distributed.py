"""Cross-replica prompt-slot serialization, against a real cache (Redis).

Two manager instances stand in for two ``api_server`` replicas sharing one
cache; the distributed lock must stop both from running a turn for the same
build session at once — the proof an in-process test can't give.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

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
def _fast_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    # Short contention wait so the "second replica refused" path returns
    # quickly instead of blocking the full default budget.
    monkeypatch.setattr(serve_transport, "PROMPT_SLOT_ACQUIRE_TIMEOUT_SECONDS", 1.0)


@pytest.fixture
def _redis_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force Redis so this exercises the real cross-replica lock regardless of
    # the env default.
    monkeypatch.setattr(factory, "CACHE_BACKEND", CacheBackendType.REDIS)


def test_second_replica_refused_then_admitted_after_release(
    tenant_context: None,  # noqa: ARG001
    _fast_acquire: None,  # noqa: ARG001
    _redis_backend: None,  # noqa: ARG001
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
            assert second is False, (
                "a second replica must be refused while the slot is held"
            )

    # A released → a queued third turn can now proceed.
    with replica_b.prompt_slot(sandbox_id, build_session_id) as third:
        assert third is True, "slot must be acquirable once the holder releases"
