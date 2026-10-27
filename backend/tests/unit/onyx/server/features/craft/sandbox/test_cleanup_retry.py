from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from docker.errors import NotFound

from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession, Sandbox
from onyx.server.features.build.db import build_session as session_db
from onyx.server.features.build.db import sandbox as sandbox_db
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.docker import docker_sandbox_manager as dsm
from onyx.server.features.build.sandbox.models import (
    SandboxCleanupCheckpoint,
    SandboxResource,
    SandboxResourceKind,
)
from onyx.server.features.build.session import manager as session_manager
from onyx.server.features.build.session import sandbox_lifecycle as lifecycle


def _sandbox() -> Sandbox:
    return Sandbox(
        id=uuid4(),
        user_id=uuid4(),
        status=SandboxStatus.RUNNING,
        provisioning_attempt_number=1,
        last_heartbeat=datetime.now(timezone.utc) - timedelta(days=1),
    )


def test_new_worker_retries_volume_removal_after_checkpoint_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _sandbox()
    docker = object.__new__(dsm.DockerSandboxManager)
    docker._docker = MagicMock()
    docker._cleanup_docker = docker._docker
    container = MagicMock()
    container.labels = {
        dsm.LABEL_SANDBOX_ID: str(sandbox.id),
        dsm.LABEL_TENANT_ID: "tenant-a",
        dsm.LABEL_K8S_MANAGED_BY: "onyx",
    }
    volume = docker._docker.volumes.get.return_value
    volume.name = "workspace"
    volume.attrs = {
        "Labels": container.labels,
        "CreatedAt": "2026-10-21T00:00:00Z",
    }
    volume.remove.side_effect = [RuntimeError("volume busy"), None]
    current_container = [container]

    def get_container(_container_id: str) -> MagicMock:
        if not current_container:
            raise NotFound("missing container")
        return container

    docker._cleanup_docker.containers.get.side_effect = get_container
    monkeypatch.setattr(
        docker,
        "_get_container",
        lambda _sandbox_id: next(iter(current_container), None),
    )
    monkeypatch.setattr(docker, "_close_all_sandbox_buses", lambda _sandbox_id: None)
    db_session = MagicMock()
    proof: dict[str, int | str | None] = {}

    def record(
        _db_session: object, _sandbox_id: object, checkpoint: SandboxCleanupCheckpoint
    ) -> bool:
        proof.update(
            provisioning_attempt_number=checkpoint.provisioning_attempt_number,
            storage_identity=checkpoint.storage_identity,
            last_heartbeat=checkpoint.last_heartbeat.isoformat()
            if checkpoint.last_heartbeat
            else None,
        )
        return True

    def remove_container(**_kwargs: object) -> None:
        assert proof
        db_session.commit.assert_called_once()
        current_container.clear()

    container.remove.side_effect = remove_container
    monkeypatch.setattr(lifecycle, "record_cleanup_checkpoint__no_commit", record)
    monkeypatch.setattr(lifecycle, "get_orphan_build_session_ids", lambda *_args: set())
    monkeypatch.setattr(
        lifecycle, "sleep_running_sandbox__no_commit", lambda *_args: True
    )
    monkeypatch.setattr(lifecycle, "clear_nextjs_ports_for_user", lambda *_args: 0)
    monkeypatch.setattr(
        lifecycle, "mark_user_sessions_idle__no_commit", lambda *_args: 0
    )

    def manager() -> MagicMock:
        worker = MagicMock(spec=SandboxManager)
        worker.supports_opencode_history_persistence = True
        worker.workspace_storage_exists.side_effect = docker.workspace_storage_exists
        worker.workspace_storage_identity.side_effect = (
            docker.workspace_storage_identity
        )
        worker.runtime_exists.side_effect = docker.runtime_exists
        worker.terminate.side_effect = docker.terminate

        def inventory(*_args: object) -> list[SandboxResource]:
            resources = [
                SandboxResource(
                    kind=SandboxResourceKind.VOLUME,
                    name=volume.name,
                    instance_id=volume.attrs["CreatedAt"],
                    sandbox_id=sandbox.id,
                    tenant_id="tenant-a",
                    created_at=datetime.now(timezone.utc),
                )
            ]
            if current_container:
                resources.insert(
                    0,
                    SandboxResource(
                        kind=SandboxResourceKind.CONTAINER,
                        name="sandbox",
                        instance_id="container-1",
                        sandbox_id=sandbox.id,
                        tenant_id="tenant-a",
                        created_at=datetime.now(timezone.utc),
                    ),
                )
            return resources

        worker.iter_resources.side_effect = inventory
        worker.terminate_observed_resources.side_effect = (
            docker.terminate_observed_resources
        )
        worker.list_session_workspaces.return_value = []
        return worker

    first = manager()
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        lifecycle.sleep_sandbox(db_session, first, sandbox, "tenant-a", MagicMock())
    first.create_opencode_history_snapshot.assert_called_once()
    assert not current_container

    retry = _sandbox()
    retry.id, retry.user_id = sandbox.id, sandbox.user_id
    retry.last_heartbeat = sandbox.last_heartbeat
    retry.cleanup_checkpoint = dict(proof)
    second = manager()
    lifecycle.sleep_sandbox(db_session, second, retry, "tenant-a", MagicMock())

    second.create_opencode_history_snapshot.assert_not_called()
    second.list_session_workspaces.assert_not_called()
    assert volume.remove.call_count == 2
    assert db_session.commit.call_count == 2


@pytest.mark.parametrize("mismatch", ["attempt", "storage", "runtime", "heartbeat"])
def test_retry_requires_matching_attempt_storage_and_absent_runtime(
    mismatch: str,
) -> None:
    sandbox = _sandbox()
    sandbox.cleanup_checkpoint = {
        "provisioning_attempt_number": 0 if mismatch == "attempt" else 1,
        "storage_identity": "old-volume" if mismatch == "storage" else "volume-v1",
        "last_heartbeat": (
            sandbox.last_heartbeat.isoformat()
            if mismatch != "heartbeat" and sandbox.last_heartbeat is not None
            else None
        ),
    }
    manager = MagicMock(spec=SandboxManager)
    manager.workspace_storage_exists.return_value = True
    manager.workspace_storage_identity.return_value = "volume-v1"
    manager.runtime_exists.return_value = mismatch == "runtime"
    manager.iter_resources.return_value = [
        SandboxResource(
            kind=SandboxResourceKind.VOLUME,
            name="volume",
            instance_id="volume-v1",
            sandbox_id=sandbox.id,
            tenant_id="tenant-a",
            created_at=datetime.now(timezone.utc),
        )
    ]
    manager.supports_opencode_history_persistence = True
    manager.create_opencode_history_snapshot.side_effect = RuntimeError(
        "checkpoint failed"
    )
    lifecycle.sleep_sandbox(MagicMock(), manager, sandbox, "tenant-a", MagicMock())
    manager.create_opencode_history_snapshot.assert_called_once()
    manager.terminate.assert_not_called()


def test_checkpoint_commit_failure_aborts_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MagicMock(spec=SandboxManager)
    manager.workspace_storage_exists.return_value = True
    manager.workspace_storage_identity.return_value = "volume-v1"
    manager.supports_opencode_history_persistence = False
    manager.list_session_workspaces.return_value = []
    sandbox = _sandbox()
    manager.iter_resources.return_value = [
        SandboxResource(
            kind=SandboxResourceKind.VOLUME,
            name="volume",
            instance_id="volume-v1",
            sandbox_id=sandbox.id,
            tenant_id="tenant-a",
            created_at=datetime.now(timezone.utc),
        )
    ]
    monkeypatch.setattr(lifecycle, "get_orphan_build_session_ids", lambda *_args: set())
    monkeypatch.setattr(
        lifecycle, "record_cleanup_checkpoint__no_commit", lambda *_args: True
    )
    db_session = MagicMock()
    db_session.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError, match="commit failed"):
        lifecycle.sleep_sandbox(db_session, manager, sandbox, "tenant-a", MagicMock())
    manager.terminate.assert_not_called()


@pytest.mark.parametrize("operation", ["upload", "delete"])
def test_activity_invalidates_failed_cleanup_before_filesystem_write(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = _sandbox()
    backend, db_session = MagicMock(spec=SandboxManager), MagicMock()
    backend.workspace_storage_exists.return_value = True
    backend.workspace_storage_identity.return_value = "volume-v1"
    backend.supports_opencode_history_persistence = False
    backend.list_session_workspaces.return_value = []
    backend.iter_resources.return_value = [
        SandboxResource(
            kind=SandboxResourceKind.VOLUME,
            name="volume",
            instance_id="volume-v1",
            sandbox_id=sandbox.id,
            tenant_id="tenant-a",
            created_at=datetime.now(timezone.utc),
        )
    ]
    backend.terminate_observed_resources.side_effect = RuntimeError(
        "container removal failed"
    )
    monkeypatch.setattr(lifecycle, "get_orphan_build_session_ids", lambda *_args: set())

    def record(
        _db_session: object, _sandbox_id: object, checkpoint: SandboxCleanupCheckpoint
    ) -> bool:
        sandbox.cleanup_checkpoint = checkpoint.model_dump(mode="json")
        return True

    monkeypatch.setattr(lifecycle, "record_cleanup_checkpoint__no_commit", record)
    with pytest.raises(RuntimeError, match="container removal failed"):
        lifecycle.sleep_sandbox(db_session, backend, sandbox, "tenant-a", MagicMock())
    assert sandbox.cleanup_checkpoint is not None

    session = BuildSession(id=uuid4(), user_id=sandbox.user_id)
    manager = object.__new__(session_manager.SessionManager)
    manager._db_session, manager._sandbox_manager = db_session, backend
    monkeypatch.setattr(
        manager, "_require_session_and_sandbox", lambda *_args: (session, sandbox)
    )
    monkeypatch.setattr(manager, "get_upload_stats", lambda *_args: (0, 0))
    monkeypatch.setattr(sandbox_db, "get_sandbox_by_id", lambda *_args: sandbox)
    events: list[str] = []
    db_session.commit.side_effect = lambda: events.append("commit")

    def lock_session(*_args: object, **_kwargs: object) -> BuildSession:
        events.append("lock")
        return session

    monkeypatch.setattr(session_manager, "get_build_session", lock_session)

    def mutate(**_kwargs: object) -> None:
        assert sandbox.cleanup_checkpoint is None
        assert events == (["commit", "lock"] if operation == "upload" else ["commit"])
        raise RuntimeError("worker died after file write")

    with pytest.raises(RuntimeError, match="worker died after file write"):
        if operation == "upload":
            backend.upload_file.side_effect = mutate
            manager.upload_file(session.id, sandbox.user_id, "new.txt", b"new")
        else:
            backend.delete_file.side_effect = mutate
            manager.delete_file(session.id, sandbox.user_id, "old.txt")

    backend.runtime_exists.return_value = False
    backend.list_session_workspaces.side_effect = RuntimeError("runtime missing")
    with pytest.raises(RuntimeError, match="runtime missing"):
        lifecycle.sleep_sandbox(db_session, backend, sandbox, "tenant-a", MagicMock())
    backend.terminate_observed_resources.assert_called_once()


@pytest.mark.parametrize("legacy", [False, True])
def test_both_heartbeat_helpers_clear_cleanup_proof(
    legacy: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = _sandbox()
    sandbox.cleanup_checkpoint = {
        "provisioning_attempt_number": 1,
        "storage_identity": "old-volume",
        "last_heartbeat": None,
    }
    db_session = MagicMock()
    monkeypatch.setattr(sandbox_db, "get_sandbox_by_id", lambda *_args: sandbox)
    db_session.query.return_value.filter.return_value.one_or_none.return_value = sandbox
    if legacy:
        session_db.update_sandbox_heartbeat(sandbox.id, db_session)
    else:
        sandbox_db.update_sandbox_heartbeat(db_session, sandbox.id)
    assert sandbox.cleanup_checkpoint is None


def test_failed_heartbeat_fence_prevents_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, db_session = MagicMock(spec=SandboxManager), MagicMock()
    backend.workspace_storage_exists.return_value = True
    backend.workspace_storage_identity.return_value = "volume-v1"
    backend.supports_opencode_history_persistence = False
    backend.list_session_workspaces.return_value = []
    db_session.execute.return_value.rowcount = 0
    sandbox = _sandbox()
    backend.iter_resources.return_value = [
        SandboxResource(
            kind=SandboxResourceKind.VOLUME,
            name="volume",
            instance_id="volume-v1",
            sandbox_id=sandbox.id,
            tenant_id="tenant-a",
            created_at=datetime.now(timezone.utc),
        )
    ]
    monkeypatch.setattr(lifecycle, "get_orphan_build_session_ids", lambda *_args: set())
    lifecycle.sleep_sandbox(db_session, backend, sandbox, "tenant-a", MagicMock())
    backend.terminate_observed_resources.assert_not_called()
    db_session.commit.assert_not_called()
