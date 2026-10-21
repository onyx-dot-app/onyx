from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.docker import docker_sandbox_manager as dsm
from onyx.server.features.build.sandbox.models import SandboxCleanupCheckpoint
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
    container = MagicMock()
    container.labels = {
        dsm.LABEL_SANDBOX_ID: str(sandbox.id),
        dsm.LABEL_TENANT_ID: "tenant-a",
    }
    volume = docker._docker.volumes.get.return_value
    volume.name = "workspace"
    volume.attrs = {
        "Labels": container.labels,
        "CreatedAt": "2026-10-21T00:00:00Z",
    }
    volume.remove.side_effect = [RuntimeError("volume busy"), None]
    current_container = [container]
    monkeypatch.setattr(
        docker,
        "_get_container",
        lambda _sandbox_id: next(iter(current_container), None),
    )
    monkeypatch.setattr(docker, "_close_all_sandbox_buses", lambda _sandbox_id: None)
    db_session = MagicMock()
    proof: dict[str, int | str] = {}

    def record(
        _db_session: object, _sandbox_id: object, checkpoint: SandboxCleanupCheckpoint
    ) -> bool:
        proof.update(
            provisioning_attempt_number=checkpoint.provisioning_attempt_number,
            storage_identity=checkpoint.storage_identity,
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
        worker.list_session_workspaces.return_value = []
        return worker

    first = manager()
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        lifecycle.sleep_sandbox(db_session, first, sandbox, "tenant-a", MagicMock())
    first.create_opencode_history_snapshot.assert_called_once()
    assert not current_container

    retry = _sandbox()
    retry.id, retry.user_id = sandbox.id, sandbox.user_id
    retry.cleanup_checkpoint = dict(proof)
    second = manager()
    lifecycle.sleep_sandbox(db_session, second, retry, "tenant-a", MagicMock())

    second.create_opencode_history_snapshot.assert_not_called()
    second.list_session_workspaces.assert_not_called()
    assert volume.remove.call_count == 2
    assert db_session.commit.call_count == 2


@pytest.mark.parametrize("mismatch", ["attempt", "storage", "runtime"])
def test_retry_requires_matching_attempt_storage_and_absent_runtime(
    mismatch: str,
) -> None:
    sandbox = _sandbox()
    sandbox.cleanup_checkpoint = {
        "provisioning_attempt_number": 0 if mismatch == "attempt" else 1,
        "storage_identity": "old-volume" if mismatch == "storage" else "volume-v1",
    }
    manager = MagicMock(spec=SandboxManager)
    manager.workspace_storage_exists.return_value = True
    manager.workspace_storage_identity.return_value = "volume-v1"
    manager.runtime_exists.return_value = mismatch == "runtime"
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
    monkeypatch.setattr(lifecycle, "get_orphan_build_session_ids", lambda *_args: set())
    monkeypatch.setattr(
        lifecycle, "record_cleanup_checkpoint__no_commit", lambda *_args: True
    )
    db_session = MagicMock()
    db_session.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError, match="commit failed"):
        lifecycle.sleep_sandbox(
            db_session, manager, _sandbox(), "tenant-a", MagicMock()
        )
    manager.terminate.assert_not_called()
