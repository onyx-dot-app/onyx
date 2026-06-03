"""Cross-replica prompt-slot serialization (distributed lock).

Proves what an in-process test cannot: two manager instances — standing in
for two ``api_server`` replicas — share one cache, so only the *distributed*
lock (not each instance's own ``threading.Lock``) can serialize their turns.
This is the boundary that stops two pods from both POSTing ``prompt_async``
for one build session and corrupting persisted conversation state.

Requires a real cache (forces the Redis backend).

    python -m dotenv -f .vscode/.env run -- pytest \
        backend/tests/external_dependency_unit/craft/test_prompt_slot_distributed.py
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
    """A manager with only serve-transport state — its own in-process lock map,
    like a fresh pod. Skips ``_initialize`` so no kube config is needed."""
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

    # Replica A holds the slot for an in-flight turn.
    slot_a = replica_a.prompt_slot(sandbox_id, build_session_id)
    assert slot_a.__enter__() is True
    try:
        # Replica B is a different instance with a different in-process lock —
        # only the distributed lock stands between them, and it must refuse.
        with replica_b.prompt_slot(sandbox_id, build_session_id) as second:
            assert second is False, (
                "a second replica must be refused while the slot is held"
            )
    finally:
        slot_a.__exit__(None, None, None)

    # A released → a queued third turn (on either replica) can now proceed.
    with replica_b.prompt_slot(sandbox_id, build_session_id) as third:
        assert third is True, "slot must be acquirable once the holder releases"
