"""Cross-replica sandbox provisioning serialization, against a real Redis.

Two ``KubernetesSandboxManager`` instances stand in for two api_server
replicas sharing one Redis. Exactly one replica may create the pod and run
the startup restore handshake; a concurrent provisioner must wait on the
per-sandbox lock and then reuse the ready pod — never stream a second
restore into the same pod (the 08fe79d8 production race).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from uuid import UUID
from uuid import uuid4

import pytest
from kubernetes.client.rest import ApiException

from onyx.cache import factory
from onyx.cache.interface import CacheBackendType
from onyx.db.enums import SandboxStatus
from onyx.server.features.build.sandbox.kubernetes import kubernetes_sandbox_manager
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import SandboxInfo
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.common.craft.payloads import default_llm_config


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
    faked against the shared cluster state; skips ``_initialize`` so no kube
    config is needed. The restore handshake and pod creation are recorded so
    tests can assert exactly-once semantics."""
    m: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    m._init_serve_state()
    monkeypatch.setattr(m, "_namespace", "test-ns", raising=False)
    monkeypatch.setattr(m, "_core_api", _FakeCoreApi(cluster), raising=False)

    def _pod_exists_and_healthy(pod_name: str) -> bool:
        with cluster.lock:
            return pod_name in cluster.ready

    def _ensure_service_exists(sandbox_id: UUID, tenant_id: str) -> None:  # noqa: ARG001
        return None

    def _provision_opencode_secret(sandbox_id: str, config_json: str) -> None:  # noqa: ARG001
        return None

    def _create_sandbox_pod(*, sandbox_id: str, tenant_id: str) -> str:  # noqa: ARG001
        return m._get_pod_name(sandbox_id)

    def _wait_for_pod_ip(pod_name: str, deadline: float) -> bool:  # noqa: ARG001
        return True

    def _restore_opencode_history_snapshot(
        sandbox_id: UUID,
        tenant_id: str,  # noqa: ARG001
        timeout_seconds: float = 300.0,  # noqa: ARG001
    ) -> bool:
        with cluster.lock:
            cluster.restores.append(sandbox_id)
        if on_restore is not None:
            on_restore()
        return True

    def _wait_for_pod_ready(pod_name: str, timeout: float = 60.0) -> bool:  # noqa: ARG001
        # Real pods flip Ready only after the sidecar handshake completes.
        with cluster.lock:
            if pod_name not in cluster.pods:
                return False
            cluster.ready.add(pod_name)
            return True

    def _wait_for_opencode_serve_ready(
        sandbox_id: UUID,  # noqa: ARG001
        timeout: float = 30.0,  # noqa: ARG001
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
        kubernetes_sandbox_manager, "SANDBOX_API_SERVER_URL", "http://api-server"
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
        llm_config=default_llm_config(),
        onyx_pat="test-pat",
    )


def test_concurrent_provision_runs_exactly_one_restore(
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
    loser = _make_replica(cluster, monkeypatch)

    results: dict[str, SandboxInfo] = {}
    errors: list[BaseException] = []

    def _run(name: str, replica: KubernetesSandboxManager) -> None:
        try:
            results[name] = _provision(replica, sandbox_id)
        except BaseException as e:
            errors.append(e)

    t_winner = threading.Thread(target=_run, args=("winner", winner))
    t_winner.start()
    assert restore_entered.wait(timeout=10)

    t_loser = threading.Thread(target=_run, args=("loser", loser))
    t_loser.start()
    time.sleep(0.5)

    # Loser must be parked on the lock while the winner is mid-restore.
    assert t_loser.is_alive()
    assert "loser" not in results
    assert cluster.pod_creates == [pod_name]
    assert cluster.restores == [sandbox_id]

    release_restore.set()
    t_winner.join(timeout=10)
    t_loser.join(timeout=10)
    assert not t_winner.is_alive() and not t_loser.is_alive()

    assert errors == []
    assert results["winner"].status == SandboxStatus.RUNNING
    assert results["loser"].status == SandboxStatus.RUNNING
    assert cluster.pod_creates == [pod_name]
    assert cluster.restores == [sandbox_id]


def test_loser_times_out_while_winner_holds_lock(
    lock_env: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _FakeCluster()
    sandbox_id = uuid4()

    restore_entered = threading.Event()
    release_restore = threading.Event()

    def _hold_restore() -> None:
        restore_entered.set()
        assert release_restore.wait(timeout=10)

    winner = _make_replica(cluster, monkeypatch, on_restore=_hold_restore)
    loser = _make_replica(cluster, monkeypatch)

    winner_result: list[SandboxInfo] = []
    t_winner = threading.Thread(
        target=lambda: winner_result.append(_provision(winner, sandbox_id))
    )
    t_winner.start()
    assert restore_entered.wait(timeout=10)
    # Patch only after the winner acquires: the constant is also the TTL.
    monkeypatch.setattr(
        kubernetes_sandbox_manager, "PROVISION_LOCK_TIMEOUT_SECONDS", 0.5
    )

    try:
        with pytest.raises(RuntimeError, match="Timed out waiting"):
            _provision(loser, sandbox_id)
    finally:
        release_restore.set()
        t_winner.join(timeout=10)

    assert len(winner_result) == 1
    assert winner_result[0].status == SandboxStatus.RUNNING
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
    # If the failed attempt orphaned the lock, the retry would time out.
    monkeypatch.setattr(
        kubernetes_sandbox_manager, "PROVISION_LOCK_TIMEOUT_SECONDS", 3.0
    )

    with pytest.raises(ApiException):
        _provision(failing, sandbox_id)

    retry = _make_replica(cluster, monkeypatch)
    info = _provision(retry, sandbox_id)

    assert info.status == SandboxStatus.RUNNING
    assert cluster.pod_creates == [pod_name]
    assert cluster.restores == [sandbox_id]
