from types import SimpleNamespace
from uuid import uuid4

import pytest

from onyx.server.features.build.sandbox.tasks import tasks


class DummyLock:
    def acquire(self, blocking: bool = False) -> bool:  # noqa: ARG002
        return True

    def owned(self) -> bool:
        return True

    def release(self) -> None:
        return None


class DummyRedisClient:
    def lock(self, *_args: object, **_kwargs: object) -> DummyLock:
        return DummyLock()


class NoCleanupManager:
    def supports_idle_cleanup(self) -> bool:
        return False


class CleanupManager:
    def __init__(self, session_ids: list) -> None:
        self._session_ids = session_ids
        self.snapshots: list[tuple] = []
        self.terminated: list = []

    def supports_idle_cleanup(self) -> bool:
        return True

    def list_session_workspaces(self, sandbox_id):
        assert sandbox_id is not None
        return self._session_ids

    def create_snapshot(self, sandbox_id, session_id, tenant_id):
        self.snapshots.append((sandbox_id, session_id, tenant_id))
        return SimpleNamespace(
            storage_path=f"snapshots/{session_id}.tar.gz",
            size_bytes=123,
        )

    def terminate(self, sandbox_id):
        self.terminated.append(sandbox_id)


def test_cleanup_idle_sandboxes_task_skips_backends_without_idle_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "get_sandbox_manager", lambda: NoCleanupManager())
    monkeypatch.setattr(
        tasks, "get_redis_client", lambda tenant_id: DummyRedisClient()
    )

    tasks.cleanup_idle_sandboxes_task.run(tenant_id="tenant-a")


def test_cleanup_idle_sandboxes_task_uses_manager_session_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox_id = uuid4()
    user_id = uuid4()
    session_ids = [uuid4(), uuid4()]
    manager = CleanupManager(session_ids)
    sandbox = SimpleNamespace(id=sandbox_id, user_id=user_id)

    class DummyDbSession:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

    class DummyDbContext:
        def __enter__(self):
            return DummyDbSession()

        def __exit__(self, exc_type, exc, tb):
            return False

    import onyx.server.features.build.db.sandbox as sandbox_db

    monkeypatch.setattr(tasks, "get_sandbox_manager", lambda: manager)
    monkeypatch.setattr(
        tasks, "get_redis_client", lambda tenant_id: DummyRedisClient()
    )
    monkeypatch.setattr(
        tasks, "get_session_with_current_tenant", lambda: DummyDbContext()
    )
    monkeypatch.setattr(
        tasks, "maybe_mark_tenant_active", lambda tenant_id, caller: None
    )
    monkeypatch.setattr(tasks, "clear_nextjs_ports_for_user", lambda db, uid: 2)
    monkeypatch.setattr(
        tasks, "mark_user_sessions_idle__no_commit", lambda db, uid: 2
    )
    monkeypatch.setattr(
        sandbox_db, "get_idle_sandboxes", lambda db, timeout: [sandbox]
    )
    monkeypatch.setattr(
        sandbox_db,
        "create_snapshot__no_commit",
        lambda db, sid, path, size: None,
    )
    monkeypatch.setattr(
        sandbox_db,
        "update_sandbox_status__no_commit",
        lambda db, sid, status: None,
    )

    tasks.cleanup_idle_sandboxes_task.run(tenant_id="tenant-a")

    assert manager.snapshots == [
        (sandbox_id, session_ids[0], "tenant-a"),
        (sandbox_id, session_ids[1], "tenant-a"),
    ]
    assert manager.terminated == [sandbox_id]
