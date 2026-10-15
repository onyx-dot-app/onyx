"""Real worker reaping and API recovery of durable Firecracker state."""

from __future__ import annotations

import shlex
import time
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from uuid import UUID

import pytest
from kubernetes import client

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryQueues, OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import BuildSessionStatus, SandboxStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import (
    SANDBOX_IDLE_TIMEOUT_SECONDS,
    SANDBOX_NAMESPACE,
)
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.sandbox import (
    get_latest_snapshot_for_session,
    get_running_sandboxes,
    get_sandbox_by_id,
)
from onyx.server.features.build.sandbox.manager import SandboxManager
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from onyx.server.features.build.session.models import SandboxStatusResponse
from shared_configs.contextvars import get_current_tenant_id
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client as http_client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    OwnedLivePod,
    assert_api_preserves_opencode_session,
    pod_exec,
    wait_for_pod_deletion,
)

_OUTPUT_PATH = "outputs/recovery-proof.txt"
_OUTPUT_BYTES = b"durable output before the VM stopped\n"
_HISTORY_PATH = "/workspace/opencode-data/cache/recovery-proof.txt"
_HISTORY_TEXT = "durable history before the VM stopped\n"


class _RuntimeIdentity(NamedTuple):
    pod_uid: str
    boot_id: UUID
    opencode_session_id: str


@pytest.fixture(autouse=True)
def _cleanup_recovery_archives(
    owned_live_pod: OwnedLivePod,
) -> Generator[None, None, None]:
    try:
        yield
    finally:
        with get_session_with_current_tenant() as db_session:
            snapshot = get_latest_snapshot_for_session(
                db_session, owned_live_pod.session_id
            )
            storage_path = snapshot.storage_path if snapshot is not None else None
        snapshots = SnapshotManager(get_default_file_store())
        if storage_path is not None:
            snapshots.delete_snapshot(storage_path)
        snapshots.delete_opencode_history_snapshot(
            get_current_tenant_id(), str(owned_live_pod.sandbox_id)
        )


def _seed_durable_state(
    manager: SandboxManager, k8s: client.CoreV1Api, owned: OwnedLivePod
) -> _RuntimeIdentity:
    manager._guest(
        owned.sandbox_id,
        "write-file",
        {"session_id": str(owned.session_id), "path": _OUTPUT_PATH},
        stdin=_OUTPUT_BYTES,
    )
    pod_exec(
        k8s,
        owned.pod_name,
        SANDBOX_NAMESPACE,
        "mkdir -p /workspace/opencode-data/cache && "
        f"printf %s {shlex.quote(_HISTORY_TEXT)} > {shlex.quote(_HISTORY_PATH)}",
    )
    with get_session_with_current_tenant() as db_session:
        session = get_build_session(
            owned.session_id, UUID(owned.api_user.id), db_session
        )
        assert session is not None
        opencode_session_id = session.opencode_session_id
        assert opencode_session_id is not None
    assert_api_preserves_opencode_session(owned, owned.session_id, opencode_session_id)
    pod = k8s.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE)
    assert pod.metadata is not None
    assert isinstance(pod.metadata.uid, str)
    assert pod.spec is not None
    assert pod.spec.runtime_class_name == "kata-fc"
    boot_id = UUID(
        pod_exec(
            k8s,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            "cat /proc/sys/kernel/random/boot_id",
        ).strip()
    )
    return _RuntimeIdentity(pod.metadata.uid, boot_id, opencode_session_id)


def _assert_api_resume_restores_durable_state(
    k8s: client.CoreV1Api,
    owned: OwnedLivePod,
    before: _RuntimeIdentity,
) -> None:
    session = BuildSessionManager.restore(owned.api_user, owned.session_id)
    assert session.status == BuildSessionStatus.ACTIVE
    assert session.session_loaded_in_sandbox is True
    assert session.sandbox is not None
    assert session.sandbox.id == str(owned.sandbox_id)
    assert session.sandbox.status == SandboxStatus.RUNNING
    pod = k8s.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE)
    assert pod.metadata is not None
    assert isinstance(pod.metadata.uid, str)
    assert pod.metadata.uid != before.pod_uid
    assert pod.spec is not None
    assert pod.spec.runtime_class_name == "kata-fc"
    boot_id = UUID(
        pod_exec(
            k8s,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            "cat /proc/sys/kernel/random/boot_id",
        ).strip()
    )
    assert boot_id != before.boot_id
    assert (
        BuildSessionManager.download_artifact(
            owned.api_user, owned.session_id, _OUTPUT_PATH
        )
        == _OUTPUT_BYTES
    )
    assert (
        pod_exec(k8s, owned.pod_name, SANDBOX_NAMESPACE, f"cat {_HISTORY_PATH}")
        == _HISTORY_TEXT
    )
    assert_api_preserves_opencode_session(
        owned, owned.session_id, before.opencode_session_id
    )


def test_idle_worker_snapshots_and_sleeps_before_api_resume(
    k8s_manager: SandboxManager,
    k8s_client: client.CoreV1Api,
    owned_live_pod: OwnedLivePod,
) -> None:
    owned = owned_live_pod
    before = _seed_durable_state(k8s_manager, k8s_client, owned)
    with get_session_with_current_tenant() as db_session:
        running_ids = {sandbox.id for sandbox in get_running_sandboxes(db_session)}
        assert running_ids == {owned.sandbox_id}, (
            "The real idle sweep requires an isolated tenant. "
            f"Refusing to sweep other running sandboxes: {running_ids}"
        )
        assert get_latest_snapshot_for_session(db_session, owned.session_id) is None
        sandbox = get_sandbox_by_id(db_session, owned.sandbox_id)
        assert sandbox is not None
        assert sandbox.user_id == UUID(owned.api_user.id)
        assert sandbox.status == SandboxStatus.RUNNING
        sandbox.last_heartbeat = datetime.now(timezone.utc) - timedelta(
            seconds=SANDBOX_IDLE_TIMEOUT_SECONDS + 60
        )
        db_session.commit()

    client_app.send_task(
        OnyxCeleryTask.CLEANUP_IDLE_SANDBOXES,
        kwargs={"tenant_id": get_current_tenant_id()},
        queue=OnyxCeleryQueues.SANDBOX,
        priority=OnyxCeleryPriority.LOW,
        expires=300,
    )

    deadline = time.monotonic() + 600
    last_status: SandboxStatus | None = None
    while time.monotonic() < deadline:
        response = http_client.get(
            f"{API_SERVER_URL}/build/sessions/{owned.session_id}/sandbox-status",
            headers=owned.api_user.headers,
            cookies=owned.api_user.cookies,
        )
        response.raise_for_status()
        last_status = SandboxStatusResponse.model_validate(response.json()).status
        if last_status == SandboxStatus.SLEEPING:
            break
        time.sleep(2)
    else:
        raise AssertionError(
            "The real heavy worker did not sleep the idle sandbox. "
            f"Last status: {last_status}. Verify the worker consumes the sandbox queue."
        )

    wait_for_pod_deletion(k8s_client, owned.pod_name)
    with get_session_with_current_tenant() as db_session:
        snapshot = get_latest_snapshot_for_session(db_session, owned.session_id)
        assert snapshot is not None
    session = next(
        session
        for session in BuildSessionManager.list_sessions(owned.api_user)
        if session.id == str(owned.session_id)
    )
    assert session.status == BuildSessionStatus.IDLE
    _assert_api_resume_restores_durable_state(k8s_client, owned, before)


def test_owned_pod_loss_recovers_last_durable_output_and_history(
    k8s_manager: SandboxManager,
    k8s_client: client.CoreV1Api,
    owned_live_pod: OwnedLivePod,
) -> None:
    owned = owned_live_pod
    before = _seed_durable_state(k8s_manager, k8s_client, owned)
    snapshot = BuildSessionManager.create_snapshot(owned.api_user, owned.session_id)
    assert snapshot is not None
    history = BuildSessionManager.create_opencode_history_snapshot(
        owned.api_user, owned.session_id
    )
    assert history.created is True
    k8s_manager._guest(
        owned.sandbox_id,
        "write-file",
        {"session_id": str(owned.session_id), "path": _OUTPUT_PATH},
        stdin=b"unsnapshotted output must not survive pod loss\n",
    )
    pod_exec(
        k8s_client,
        owned.pod_name,
        SANDBOX_NAMESPACE,
        f"printf unsnapshotted-history > {_HISTORY_PATH}",
    )
    k8s_client.delete_namespaced_pod(
        owned.pod_name,
        SANDBOX_NAMESPACE,
        body=client.V1DeleteOptions(
            preconditions=client.V1Preconditions(uid=before.pod_uid)
        ),
    )
    wait_for_pod_deletion(k8s_client, owned.pod_name)
    with get_session_with_current_tenant() as db_session:
        sandbox = get_sandbox_by_id(db_session, owned.sandbox_id)
        assert sandbox is not None
        assert sandbox.status == SandboxStatus.RUNNING
    _assert_api_resume_restores_durable_state(k8s_client, owned, before)
