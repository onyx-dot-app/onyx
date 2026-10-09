"""Cross-replica sandbox provisioning serialization, against a real Redis.

Two ``KubernetesSandboxManager`` instances stand in for two api_server
replicas sharing one Redis. Exactly one replica may create the pod and run
the startup restore handshake; a concurrent provisioner fails fast with
``SandboxProvisionContentionError`` (never streams a second restore into the
same pod — the 08fe79d8 production race) and a later retry reuses the ready
pod without re-restoring.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from kubernetes.client.rest import ApiException

from onyx.cache import factory
from onyx.cache.interface import CacheBackendType
from onyx.db.enums import SandboxStatus
from onyx.server.features.build.sandbox.kubernetes import kubernetes_sandbox_manager
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import (
    SandboxInfo,
    SandboxProvisionContentionError,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


class _FakeCluster:
    """Shared fake cluster state: pod existence/readiness + call records."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pods: set[str] = set()
        self.ready: set[str] = set()
        self.pod_creates: list[str] = []
        self.restores: list[UUID] = []


class _FakeCoreApi:
    def __init__(self, cluster: _FakeCluster) -> None:
        self._cluster = cluster

    def create_namespaced_pod(self, namespace: str, body: object) -> None:  # noqa: ARG002
        pod_name = str(body)
        with self._cluster.lock:
            if pod_name in self._cluster.pods:
                raise ApiException(status=409, reason="Conflict")
            self._cluster.pods.add(pod_name)
            self._cluster.pod_creates.append(pod_name)


def _make_replica(
    cluster: _FakeCluster,
    monkeypatch: pytest.MonkeyPatch,
    *,
    on_restore: Callable[[], None] | None = None,
) -> KubernetesSandboxManager:
    """A fresh manager (like a separate api_server pod) with all k8s I/O
    faked against the shared cluster state; skips ``__init__`` so no kube
    config is needed. The restore handshake and pod creation are recorded so
    tests can assert exactly-once semantics."""
    m: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    m._init_serve_state()
    monkeypatch.setattr(m, "_namespace", "test-ns", raising=False)
    monkeypatch.setattr(m, "_core_api", _FakeCoreApi(cluster), raising=False)

    def _pod_exists_and_healthy(pod_name: str) -> bool:
        with cluster.lock:
            return pod_name in cluster.ready

    def _ensure_service_exists(
        sandbox_id: UUID,  # noqa: ARG001
        tenant_id: str,  # noqa: ARG001
        deadline: float,  # noqa: ARG001
    ) -> None:
        return None

    def _provision_opencode_secret(sandbox_id: str, config_json: str) -> None:  # noqa: ARG001
        return None

    def _create_sandbox_pod(
        *,
        sandbox_id: str,
        tenant_id: str,  # noqa: ARG001
        provisioning_attempt_number: int,  # noqa: ARG001
    ) -> str:
        return m._get_pod_name(sandbox_id)

    def _wait_for_pod_ip(pod_name: str, deadline: float) -> bool:  # noqa: ARG001
        return True

    def _restore_opencode_history_snapshot(
        sandbox_id: UUID,
        tenant_id: str,  # noqa: ARG001
        timeout_seconds: float,  # noqa: ARG001
    ) -> bool:
        with cluster.lock:
            cluster.restores.append(sandbox_id)
        if on_restore is not None:
            on_restore()
        return True

    def _wait_for_pod_ready(pod_name: str, deadline: float) -> bool:  # noqa: ARG001
        # Real pods flip Ready only after the sidecar handshake completes.
        with cluster.lock:
            if pod_name not in cluster.pods:
                return False
            cluster.ready.add(pod_name)
            return True

    def _wait_for_opencode_serve_ready(
        sandbox_id: UUID,  # noqa: ARG001
        timeout: float,  # noqa: ARG001
    ) -> bool:
        return True

    monkeypatch.setattr(m, "_pod_exists_and_healthy", _pod_exists_and_healthy)
    monkeypatch.setattr(m, "_ensure_service_exists", _ensure_service_exists)
    monkeypatch.setattr(m, "_provision_opencode_secret", _provision_opencode_secret)
    monkeypatch.setattr(m, "_create_sandbox_pod", _create_sandbox_pod)
    monkeypatch.setattr(m, "_wait_for_pod_ip", _wait_for_pod_ip)
    monkeypatch.setattr(
        m, "restore_opencode_history_snapshot", _restore_opencode_history_snapshot
    )
    monkeypatch.setattr(m, "_wait_for_pod_ready", _wait_for_pod_ready)
    monkeypatch.setattr(
        m, "_wait_for_opencode_serve_ready", _wait_for_opencode_serve_ready
    )
    return m


@pytest.fixture
def lock_env(
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant context + Redis backend forced on + the provisioning
    preconditions (URL/proxy host) satisfied."""
    monkeypatch.setattr(factory, "CACHE_BACKEND", CacheBackendType.REDIS)
    monkeypatch.setattr(
        kubernetes_sandbox_manager, "ONYX_SERVER_URL", "http://api-server"
    )
    monkeypatch.setattr(
        kubernetes_sandbox_manager, "SANDBOX_PROXY_HOST", "sandbox-proxy"
    )


def _provision(
    replica: KubernetesSandboxManager,
    sandbox_id: UUID,
) -> SandboxInfo:
    return replica.provision(
        sandbox_id=sandbox_id,
        user_id=uuid4(),
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        onyx_pat="test-pat",
        provisioning_attempt_number=1,
    )


def test_concurrent_provision_fails_fast_and_restore_runs_once(
    lock_env: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _FakeCluster()
    sandbox_id = uuid4()
    pod_name = f"sandbox-{str(sandbox_id)[:8]}"

    restore_entered = threading.Event()
    release_restore = threading.Event()

    def _hold_restore() -> None:
        restore_entered.set()
        assert release_restore.wait(timeout=10)

    winner = _make_replica(cluster, monkeypatch, on_restore=_hold_restore)
    contender = _make_replica(cluster, monkeypatch)

    winner_result: list[SandboxInfo] = []
    t_winner = threading.Thread(
        target=lambda: winner_result.append(_provision(winner, sandbox_id))
    )
    t_winner.start()
    assert restore_entered.wait(timeout=10)

    # Contender bounces off the held lock instead of parking; the winner's
    # restore stays the only one.
    try:
        with pytest.raises(SandboxProvisionContentionError):
            _provision(contender, sandbox_id)
        assert cluster.pod_creates == [pod_name]
        assert cluster.restores == [sandbox_id]
    finally:
        release_restore.set()
        t_winner.join(timeout=10)
    assert not t_winner.is_alive()

    assert len(winner_result) == 1
    assert winner_result[0].status == SandboxStatus.RUNNING

    # Retry after the winner finished: reuses the ready pod, no second
    # create or restore.
    retry_result = _provision(contender, sandbox_id)
    assert retry_result.status == SandboxStatus.RUNNING
    assert cluster.pod_creates == [pod_name]
    assert cluster.restores == [sandbox_id]


def test_lock_released_after_provision_failure(
    lock_env: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _FakeCluster()
    sandbox_id = uuid4()
    pod_name = f"sandbox-{str(sandbox_id)[:8]}"

    failing = _make_replica(cluster, monkeypatch)

    def _boom(sandbox_id: str, config_json: str) -> None:  # noqa: ARG001
        raise ApiException(status=500, reason="secret create failed")

    monkeypatch.setattr(failing, "_provision_opencode_secret", _boom)

    with pytest.raises(ApiException):
        _provision(failing, sandbox_id)

    # If the failed attempt orphaned the lock, this retry would raise
    # SandboxProvisionContentionError instead of provisioning.
    retry = _make_replica(cluster, monkeypatch)
    info = _provision(retry, sandbox_id)

    assert info.status == SandboxStatus.RUNNING
    assert cluster.pod_creates == [pod_name]
    assert cluster.restores == [sandbox_id]
