"""Deleting a user removes the user's Craft snapshot blobs from the file store
and purges the user's Firecracker harness sandbox."""

from __future__ import annotations

import io
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db import users as users_module
from onyx.db.enums import BuildSessionStatus, SandboxStatus
from onyx.db.models import BuildSession, Snapshot, User
from onyx.db.users import delete_user_from_db
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.server.features.build.sandbox.snapshot_manager import (
    SNAPSHOT_FILE_TYPE,
    SnapshotManager,
    delete_sandbox_blobs_best_effort,
)
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user


def _seed_user_blobs(
    db_session: Session, file_store: FileStore, user: User
) -> list[str]:
    """Create a sandbox, a session with one snapshot, and opencode history."""
    sandbox = make_sandbox(db_session, user, status=SandboxStatus.SLEEPING)
    session_row = BuildSession(
        id=uuid4(),
        user_id=user.id,
        name="user-delete",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(session_row)
    db_session.commit()

    snapshot_manager = SnapshotManager(file_store)
    _, snapshot_path, _ = snapshot_manager.persist_snapshot_from_stream(
        io.BytesIO(b"snapshot-bytes"), str(sandbox.id), get_current_tenant_id()
    )
    history_path, _ = snapshot_manager.persist_opencode_snapshot_from_stream(
        io.BytesIO(b"history-bytes"), str(sandbox.id), get_current_tenant_id()
    )
    db_session.add(
        Snapshot(
            id=uuid4(),
            session_id=session_row.id,
            storage_path=snapshot_path,
            size_bytes=14,
        )
    )
    db_session.commit()
    return [snapshot_path, history_path]


def _has_blob(file_store: FileStore, path: str) -> bool:
    return file_store.has_file(path, FileOrigin.SANDBOX_SNAPSHOT, SNAPSHOT_FILE_TYPE)


def test_delete_user_removes_sandbox_blobs(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    file_store = get_default_file_store()
    file_store.initialize()
    users: list[User] = []
    seeded_paths: list[str] = []
    try:
        deleted_user = make_user(db_session, standard_account=True)
        users.append(deleted_user)
        other_user = make_user(db_session, standard_account=True)
        users.append(other_user)
        db_session.commit()
        deleted_paths = _seed_user_blobs(db_session, file_store, deleted_user)
        seeded_paths += deleted_paths
        other_paths = _seed_user_blobs(db_session, file_store, other_user)
        seeded_paths += other_paths
        assert all(_has_blob(file_store, p) for p in seeded_paths)

        delete_user_from_db(deleted_user, db_session)
        users.remove(deleted_user)

        assert not any(_has_blob(file_store, p) for p in deleted_paths)
        assert all(_has_blob(file_store, p) for p in other_paths)
    finally:
        db_session.rollback()
        for user in users:
            delete_user_from_db(user, db_session)
        delete_sandbox_blobs_best_effort(seeded_paths)


def test_delete_user_purges_the_harness_sandbox(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    purged: list[dict[UUID, list[UUID]]] = []
    monkeypatch.setattr(
        users_module, "purge_harness_sandboxes_in_background", purged.append
    )
    user = make_user(db_session, standard_account=True)
    try:
        sandbox = make_sandbox(db_session, user, status=SandboxStatus.SLEEPING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=user.id,
            name="harness-purge",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(session_row)
        db_session.commit()
        sandbox_id, session_id = sandbox.id, session_row.id

        delete_user_from_db(user, db_session)

        assert purged == [{sandbox_id: [session_id]}]
    finally:
        db_session.rollback()
        if db_session.get(User, user.id) is not None:
            delete_user_from_db(user, db_session)
