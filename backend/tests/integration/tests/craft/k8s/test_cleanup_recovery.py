"""Recover real session files and opencode history after cleanup and worker loss."""

import shlex
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from kubernetes import client
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import MessageType, OnyxRedisLocks
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildMessage, BuildSession, Sandbox
from onyx.server.features.build.configs import (
    SANDBOX_BACKEND,
    SANDBOX_IDLE_TIMEOUT_SECONDS,
    SANDBOX_NAMESPACE,
    SandboxBackend,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.session.resource_cleanup import RESOURCE_GRACE_SECONDS
from tests.common.craft.cleanup_worker import (
    APP_NAMESPACE,
    require_isolated_cleanup_deployment,
    run_cleanup,
    wait_for_resource_grace,
)
from tests.common.craft.cleanup_worker import (
    isolated_cleanup_deployment as isolated_cleanup_deployment,
)
from tests.common.craft.kubernetes_resources import TEST_FINALIZER, CleanupNamespace
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    OwnedLivePod,
    pod_exec,
    wait_for_pod_deletion,
)

require_isolated_cleanup_deployment()
pytestmark = [
    pytest.mark.skipif(
        SANDBOX_BACKEND != SandboxBackend.KUBERNETES, reason="Kubernetes only"
    ),
    pytest.mark.usefixtures("isolated_cleanup_deployment", "tenant_context"),
]


def _write_marker(
    core: client.CoreV1Api, pod: str, session_id: UUID, marker: str
) -> None:
    base = f"/workspace/sessions/{session_id}"
    for directory in ("outputs", "attachments"):
        path = f"{base}/{directory}/cleanup-marker.txt"
        result = pod_exec(
            core,
            pod,
            SANDBOX_NAMESPACE,
            f"printf %s {shlex.quote(marker)} > {path} && cat {path}",
        )
        assert result == marker


def _assert_marker(
    core: client.CoreV1Api, pod: str, session_id: UUID, marker: str
) -> None:
    for directory in ("outputs", "attachments"):
        path = f"/workspace/sessions/{session_id}/{directory}/cleanup-marker.txt"
        assert pod_exec(core, pod, SANDBOX_NAMESPACE, f"cat {path}") == marker


def test_idle_cleanup_restores_two_sessions_and_their_opencode_history(
    owned_live_pod: OwnedLivePod,
    k8s_client: client.CoreV1Api,
    k8s_manager: KubernetesSandboxManager,
    db_session: Session,
) -> None:
    owned = owned_live_pod
    original = k8s_client.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE)
    db_session.add(
        BuildMessage(
            session_id=owned.session_id,
            turn_index=0,
            type=MessageType.USER,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "first session checkpoint"},
            },
        )
    )
    db_session.commit()
    second_id, sandbox_id = BuildSessionManager.create_with_sandbox(owned.api_user)
    assert sandbox_id == owned.sandbox_id
    assert second_id != owned.session_id
    db_session.expire_all()
    history_ids: dict[UUID, str] = {}
    for session_id, marker in (
        (owned.session_id, "first-session"),
        (second_id, "second-session"),
    ):
        _write_marker(k8s_client, owned.pod_name, session_id, marker)
        session = db_session.get(BuildSession, session_id)
        assert session is not None and session.opencode_session_id is not None
        history_ids[session_id] = session.opencode_session_id
    sandbox = db_session.get(Sandbox, sandbox_id)
    assert sandbox is not None
    sandbox.last_heartbeat = datetime.now(timezone.utc) - timedelta(
        seconds=SANDBOX_IDLE_TIMEOUT_SECONDS + 60
    )
    db_session.commit()

    run_cleanup(k8s_client)

    db_session.expire_all()
    db_session.refresh(sandbox)
    assert sandbox.status == SandboxStatus.SLEEPING
    wait_for_pod_deletion(k8s_client, owned.pod_name, SANDBOX_NAMESPACE)
    for session_id, marker in (
        (owned.session_id, "first-session"),
        (second_id, "second-session"),
    ):
        response = BuildSessionManager.restore(owned.api_user, session_id)
        assert response.session_loaded_in_sandbox
        _assert_marker(k8s_client, owned.pod_name, session_id, marker)
        assert (
            k8s_manager.ensure_opencode_session(
                sandbox_id, session_id, history_ids[session_id]
            )
            == history_ids[session_id]
        )
    replacement = k8s_client.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE)
    assert replacement.metadata.uid != original.metadata.uid


def test_failed_cleanup_retains_checkpoint_across_worker_restart_and_restores_files(
    owned_live_pod: OwnedLivePod,
    k8s_client: client.CoreV1Api,
    db_session: Session,
) -> None:
    owned = owned_live_pod
    core = k8s_client
    cluster = CleanupNamespace(SANDBOX_NAMESPACE, core, KubernetesSandboxManager())
    original = core.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE)
    _write_marker(core, owned.pod_name, owned.session_id, "retained-failed-work")
    lease = get_cache_backend(tenant_id="public").lock(
        OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK,
        timeout=RESOURCE_GRACE_SECONDS + 1800,
    )
    assert lease.acquire(blocking=True, blocking_timeout=30)
    try:
        wait_for_resource_grace(core, owned.pod_name, SANDBOX_NAMESPACE)
        database = pod_exec(
            core,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            "find /workspace/opencode-data -name '*.db' -type f -print -quit",
            container="sidecar",
        ).strip()
        assert database.startswith("/workspace/opencode-data/"), database
        database = shlex.quote(database)
        mode = pod_exec(
            core,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            f"stat -c %a {database}",
            container="sidecar",
        ).strip()
        assert mode.isdigit()
        pod_exec(
            core,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            f"chmod 000 {database}",
            container="sidecar",
        )
        sandbox = db_session.get(Sandbox, owned.sandbox_id)
        assert sandbox is not None
        sandbox.status = SandboxStatus.FAILED
        sandbox.provisioning_attempt_number += 1
        db_session.commit()
        lease.release()
        try:
            run_cleanup(core)
            assert (
                core.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE).metadata.uid
                == original.metadata.uid
            )
            db_session.expire_all()
            db_session.refresh(sandbox)
            assert sandbox.cleanup_checkpoint is None
        finally:
            pod_exec(
                core,
                owned.pod_name,
                SANDBOX_NAMESPACE,
                f"chmod {mode} {database}",
                container="sidecar",
            )

        cache = get_cache_backend(tenant_id="public")
        for resource in cluster.manager.iter_resources(
            "public", time.monotonic() + 30, owned.sandbox_id
        ):
            cache.delete(
                f"sandbox_cleanup_retry:{resource.kind.value}:{resource.name}:{resource.instance_id}"
            )
        core.patch_namespaced_service(
            owned.pod_name,
            SANDBOX_NAMESPACE,
            {"metadata": {"finalizers": [TEST_FINALIZER]}},
        )
        run_cleanup(core)
        db_session.expire_all()
        db_session.refresh(sandbox)
        assert sandbox.status == SandboxStatus.FAILED
        checkpoint = sandbox.cleanup_checkpoint
        assert checkpoint is not None
        assert checkpoint["storage_identity"] == original.metadata.uid
        assert (
            checkpoint["provisioning_attempt_number"]
            == sandbox.provisioning_attempt_number
        )
        assert cluster.absent("pod", owned.pod_name)
        assert (
            core.read_namespaced_service(
                owned.pod_name, SANDBOX_NAMESPACE
            ).metadata.deletion_timestamp
            is not None
        )
        db_session.commit()

        workers = core.list_namespaced_pod(
            APP_NAMESPACE, label_selector="app=celery-worker-heavy"
        ).items
        workers = [pod for pod in workers if pod.metadata.deletion_timestamp is None]
        assert len(workers) == 1
        worker = workers[0]
        core.delete_namespaced_pod(
            worker.metadata.name,
            APP_NAMESPACE,
            body=client.V1DeleteOptions(
                grace_period_seconds=0,
                preconditions=client.V1Preconditions(uid=worker.metadata.uid),
            ),
        )
        deadline = time.monotonic() + 120
        while True:
            replacements = core.list_namespaced_pod(
                APP_NAMESPACE, label_selector="app=celery-worker-heavy"
            ).items
            if any(
                pod.metadata.uid != worker.metadata.uid
                and pod.status.container_statuses
                and all(status.ready for status in pod.status.container_statuses)
                for pod in replacements
            ):
                break
            assert time.monotonic() < deadline, "Cleanup worker did not restart"
            time.sleep(1)
        run_cleanup(core)
        db_session.expire_all()
        db_session.refresh(sandbox)
        assert sandbox.cleanup_checkpoint == checkpoint
        core.patch_namespaced_service(
            owned.pod_name, SANDBOX_NAMESPACE, {"metadata": {"finalizers": None}}
        )
        cluster.wait_absent("service", owned.pod_name)

        response = BuildSessionManager.restore(owned.api_user, owned.session_id)
        assert response.session_loaded_in_sandbox
        _assert_marker(core, owned.pod_name, owned.session_id, "retained-failed-work")
        db_session.expire_all()
        db_session.refresh(sandbox)
        assert sandbox.status == SandboxStatus.RUNNING
        assert sandbox.cleanup_checkpoint is None
        assert (
            core.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE).metadata.uid
            != original.metadata.uid
        )
    finally:
        if lease.owned():
            lease.release()
        if not cluster.absent("service", owned.pod_name):
            service = core.read_namespaced_service(owned.pod_name, SANDBOX_NAMESPACE)
            if TEST_FINALIZER in (service.metadata.finalizers or []):
                core.patch_namespaced_service(
                    owned.pod_name,
                    SANDBOX_NAMESPACE,
                    {"metadata": {"finalizers": None}},
                )
