"""Session lifecycle (DB-bound half).

Drives ``SessionManager`` end-to-end against a real Postgres + Redis with a
``StubSandboxManager`` standing in for the pod backend. Covers session create,
empty-session reuse, delete cascade, snapshot blob cleanup, port allocation,
the per-user Redis lock, idle-restore status flip, and the sandbox-reset path.
"""

from __future__ import annotations

import io
import logging
from typing import Callable
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.configs.constants import MessageType
from onyx.db.enums import ArtifactType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.enums import SessionOrigin
from onyx.db.models import Artifact
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import Snapshot
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.build.db.build_session import allocate_nextjs_port
from onyx.server.features.build.db.build_session import get_user_build_sessions
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.user_library import USER_LIBRARY_MOUNT_PATH
from onyx.server.features.build.session.api import restore_session
from onyx.server.features.build.session.manager import SessionManager
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.redis_helpers import (
    assert_lock_serializes_two_threads,
)

# Built-in skill rows are seeded by ``setup_postgres`` (run once per
# tenant in ``full_setup``) and persist across tests. The session
# lifecycle tests below tolerate their presence — assertions match on
# specifics, not on an empty fileset.


# =============================================================================
# Create
# =============================================================================


class TestCreateSession:
    def test_create_session_initializes_sandbox_row(
        self,
        db_session: Session,
        test_user: User,
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        # No sandbox yet for this user.
        assert get_sandbox_by_user_id(db_session, test_user.id) is None

        # Predict the sandbox row id by configuring provision_returns AFTER
        # the row is created; instead, we configure provision_returns to a
        # placeholder and assert by looking up the user's sandbox row.
        stub_sandbox_manager.provision_returns = SandboxInfo(
            sandbox_id=uuid4(),
            directory_path="/tmp/sandbox",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )
        stub_sandbox_manager.setup_session_workspace_silent = True
        stub_sandbox_manager.write_files_to_sandbox_silent = True

        sm = session_manager_with_stub
        build_session = sm.create_session__no_commit(user_id=test_user.id)
        db_session.commit()
        db_session.refresh(build_session)

        sandbox_row = get_sandbox_by_user_id(db_session, test_user.id)
        assert sandbox_row is not None
        assert sandbox_row.user_id == test_user.id
        # Status was set to RUNNING by _provision_sandbox.
        assert sandbox_row.status == SandboxStatus.RUNNING
        # provision() was called exactly once for this first creation.
        assert stub_sandbox_manager.provision_count == 1
        assert build_session.user_id == test_user.id
        assert build_session.opencode_session_id == "stub-opencode-session"
        assert stub_sandbox_manager.ensure_opencode_session_count == 1
        assert stub_sandbox_manager.last_ensure_opencode_session_payload == {
            "sandbox_id": sandbox_row.id,
            "session_id": build_session.id,
            "opencode_session_id": None,
        }

    def test_create_session_reuses_existing_sandbox(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        # Pre-existing RUNNING sandbox for the user.
        existing = sandbox(user=test_user, status=SandboxStatus.RUNNING)
        existing_id = existing.id

        stub_sandbox_manager.health_check_returns = True
        stub_sandbox_manager.setup_session_workspace_silent = True
        stub_sandbox_manager.write_files_to_sandbox_silent = True
        # provision_returns NOT configured — any provision() call would raise.

        sm = session_manager_with_stub
        new_session = sm.create_session__no_commit(user_id=test_user.id)
        db_session.commit()
        db_session.refresh(new_session)

        # Same single sandbox row for this user.
        rows = db_session.query(Sandbox).filter(Sandbox.user_id == test_user.id).all()
        assert len(rows) == 1
        assert rows[0].id == existing_id

        assert stub_sandbox_manager.provision_count == 0
        assert stub_sandbox_manager.health_check_count >= 1
        assert new_session.opencode_session_id == "stub-opencode-session"
        assert stub_sandbox_manager.ensure_opencode_session_count == 1
        assert stub_sandbox_manager.last_ensure_opencode_session_payload == {
            "sandbox_id": existing_id,
            "session_id": new_session.id,
            "opencode_session_id": None,
        }


# =============================================================================
# Empty-session reuse
# =============================================================================


class TestEmptySessionReuse:
    def test_empty_session_reused_when_sandbox_healthy_and_workspace_exists(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        # Seed an existing empty session + RUNNING sandbox.
        sandbox_row = sandbox(user=test_user, status=SandboxStatus.RUNNING)
        existing_empty = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="pre-provisioned",
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id="stale-opencode-session",
        )
        db_session.add(existing_empty)
        db_session.commit()

        stub_sandbox_manager.health_check_returns = True
        stub_sandbox_manager.session_workspace_exists_returns = True
        stub_sandbox_manager.ensure_opencode_session_returns = (
            "refreshed-opencode-session"
        )
        stub_sandbox_manager.write_files_to_sandbox_silent = True

        sm = session_manager_with_stub
        result = sm.get_or_create_empty_session(user_id=test_user.id)
        db_session.commit()
        db_session.refresh(result)

        assert result.id == existing_empty.id
        assert result.opencode_session_id == "refreshed-opencode-session"
        assert stub_sandbox_manager.last_ensure_opencode_session_payload == {
            "sandbox_id": sandbox_row.id,
            "session_id": existing_empty.id,
            "opencode_session_id": "stale-opencode-session",
        }
        # No new sandbox was provisioned, and only one BuildSession row exists
        # for this user.
        rows = (
            db_session.query(BuildSession)
            .filter(BuildSession.user_id == test_user.id)
            .all()
        )
        assert len(rows) == 1
        assert stub_sandbox_manager.provision_count == 0
        reused_sandbox = get_sandbox_by_user_id(db_session, test_user.id)
        assert reused_sandbox is not None
        assert sandbox_row.id == reused_sandbox.id

    def test_stale_empty_session_replaced_when_workspace_missing(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        # Regression for SHA ff3b82d15a: workspace missing on disk despite
        # the sandbox row claiming RUNNING => delete stale empty session,
        # create a fresh one (which reuses the still-healthy sandbox row).
        sandbox_row = sandbox(user=test_user, status=SandboxStatus.RUNNING)
        stale_empty = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="stale-pre-provisioned",
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id="stale-opencode-session",
        )
        db_session.add(stale_empty)
        db_session.commit()
        stale_id = stale_empty.id

        stub_sandbox_manager.health_check_returns = True
        stub_sandbox_manager.session_workspace_exists_returns = False
        stub_sandbox_manager.supports_opencode_history_persistence = True
        stub_sandbox_manager.cleanup_session_workspace_silent = True
        stub_sandbox_manager.setup_session_workspace_silent = True
        stub_sandbox_manager.write_files_to_sandbox_silent = True

        sm = session_manager_with_stub
        new_session = sm.get_or_create_empty_session(user_id=test_user.id)
        db_session.commit()

        # Stale session is gone; new one took its place.
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == stale_id)
            .one_or_none()
            is None
        )
        assert new_session.id != stale_id

        # Sandbox row reused (still RUNNING — health check passed at the
        # create_session step too).
        reused_sandbox = get_sandbox_by_user_id(db_session, test_user.id)
        assert reused_sandbox is not None
        assert reused_sandbox.id == sandbox_row.id
        assert stub_sandbox_manager.delete_opencode_session_count == 1
        assert stub_sandbox_manager.last_delete_opencode_session_payload == {
            "sandbox_id": sandbox_row.id,
            "session_id": stale_id,
            "opencode_session_id": "stale-opencode-session",
        }
        assert stub_sandbox_manager.create_opencode_history_snapshot_count == 0
        assert stub_sandbox_manager.cleanup_session_workspace_count == 1


# =============================================================================
# Delete
# =============================================================================


class TestDeleteSession:
    def test_delete_session_cascades_messages_and_artifacts(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="cascading",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(session_row)
        db_session.commit()

        # Attach a BuildMessage and an Artifact.
        msg = BuildMessage(
            id=uuid4(),
            session_id=session_row.id,
            turn_index=0,
            type=MessageType.USER,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "hi"},
            },
        )
        artifact = Artifact(
            id=uuid4(),
            session_id=session_row.id,
            type=ArtifactType.MARKDOWN,
            path="output.md",
            name="output.md",
        )
        db_session.add_all([msg, artifact])
        db_session.commit()
        msg_id = msg.id
        artifact_id = artifact.id
        session_id = session_row.id

        stub_sandbox_manager.cleanup_session_workspace_silent = True

        sm = session_manager_with_stub
        deleted = sm.delete_session(session_id=session_id, user_id=test_user.id)
        db_session.commit()
        assert deleted is True

        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_id)
            .one_or_none()
            is None
        )
        assert (
            db_session.query(BuildMessage)
            .filter(BuildMessage.id == msg_id)
            .one_or_none()
            is None
        )
        assert (
            db_session.query(Artifact).filter(Artifact.id == artifact_id).one_or_none()
            is None
        )

    def test_delete_session_deletes_live_opencode_session_best_effort(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        sandbox_row = sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="opencode-owner",
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id="ses_to_delete",
        )
        db_session.add(session_row)
        db_session.commit()

        stub_sandbox_manager.supports_opencode_history_persistence = True
        stub_sandbox_manager.cleanup_session_workspace_silent = True

        deleted = session_manager_with_stub.delete_session(
            session_id=session_row.id, user_id=test_user.id
        )

        assert deleted is True
        assert stub_sandbox_manager.delete_opencode_session_count == 1
        assert stub_sandbox_manager.last_delete_opencode_session_payload == {
            "sandbox_id": sandbox_row.id,
            "session_id": session_row.id,
            "opencode_session_id": "ses_to_delete",
        }
        assert stub_sandbox_manager.create_opencode_history_snapshot_count == 0
        assert stub_sandbox_manager.cleanup_session_workspace_count == 1
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_row.id)
            .one_or_none()
            is None
        )

    def test_delete_session_ignores_live_opencode_delete_failure(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="opencode-delete-fails",
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id="ses_delete_fails",
        )
        db_session.add(session_row)
        db_session.commit()

        stub_sandbox_manager.cleanup_session_workspace_silent = True
        stub_sandbox_manager.delete_opencode_session_returns = RuntimeError(
            "opencode offline"
        )

        with caplog.at_level(logging.WARNING):
            deleted = session_manager_with_stub.delete_session(
                session_id=session_row.id, user_id=test_user.id
            )

        assert deleted is True
        assert stub_sandbox_manager.delete_opencode_session_count == 1
        assert stub_sandbox_manager.cleanup_session_workspace_count == 1
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_row.id)
            .one_or_none()
            is None
        )
        assert any(
            "Best-effort opencode session delete failed" in r.getMessage()
            for r in caplog.records
        )

    def test_delete_session_ignores_live_opencode_delete_false(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="opencode-delete-false",
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id="ses_delete_false",
        )
        db_session.add(session_row)
        db_session.commit()

        stub_sandbox_manager.cleanup_session_workspace_silent = True
        stub_sandbox_manager.delete_opencode_session_returns = False

        with caplog.at_level(logging.WARNING):
            deleted = session_manager_with_stub.delete_session(
                session_id=session_row.id, user_id=test_user.id
            )

        assert deleted is True
        assert stub_sandbox_manager.delete_opencode_session_count == 1
        assert stub_sandbox_manager.cleanup_session_workspace_count == 1
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_row.id)
            .one_or_none()
            is None
        )
        assert any(
            "Best-effort opencode session delete returned false" in r.getMessage()
            for r in caplog.records
        )

    def test_delete_session_refuses_active_prompt_slot(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="busy-session",
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id="busy-opencode",
        )
        db_session.add(session_row)
        db_session.commit()

        stub_sandbox_manager.supports_opencode_history_persistence = True
        stub_sandbox_manager.prompt_slot_returns = False

        with pytest.raises(OnyxError) as exc_info:
            session_manager_with_stub.delete_session(
                session_id=session_row.id, user_id=test_user.id
            )

        assert exc_info.value.error_code == OnyxErrorCode.CONFLICT
        assert stub_sandbox_manager.delete_opencode_session_count == 0
        assert stub_sandbox_manager.create_opencode_history_snapshot_count == 0
        assert stub_sandbox_manager.cleanup_session_workspace_count == 0
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_row.id)
            .one_or_none()
            is not None
        )

    def test_delete_session_allows_sleeping_sandbox_with_durable_opencode_history(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.SLEEPING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="sleeping-opencode-owner",
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id="ses_sleeping",
        )
        db_session.add(session_row)
        db_session.flush()
        db_session.add(
            BuildMessage(
                session_id=session_row.id,
                turn_index=0,
                type=MessageType.ASSISTANT,
                message_metadata={
                    "type": "agent_message",
                    "content": {"type": "text", "text": "built"},
                },
            )
        )
        db_session.commit()

        stub_sandbox_manager.supports_opencode_history_persistence = True

        deleted = session_manager_with_stub.delete_session(
            session_id=session_row.id, user_id=test_user.id
        )
        db_session.commit()

        assert deleted is True
        assert stub_sandbox_manager.delete_opencode_session_count == 0
        assert stub_sandbox_manager.create_opencode_history_snapshot_count == 0
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_row.id)
            .one_or_none()
            is None
        )

    def test_delete_session_allows_empty_session_in_sleeping_sandbox(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.SLEEPING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="sleeping-empty-session",
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id="prewarmed-empty-opencode",
        )
        db_session.add(session_row)
        db_session.commit()

        stub_sandbox_manager.supports_opencode_history_persistence = True

        deleted = session_manager_with_stub.delete_session(
            session_id=session_row.id, user_id=test_user.id
        )
        db_session.commit()

        assert deleted is True
        assert stub_sandbox_manager.delete_opencode_session_count == 0
        assert stub_sandbox_manager.create_opencode_history_snapshot_count == 0
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_row.id)
            .one_or_none()
            is None
        )

    def test_delete_session_allows_active_established_session_without_opencode_id(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="missing-opencode-id",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(session_row)
        db_session.flush()
        db_session.add(
            BuildMessage(
                session_id=session_row.id,
                turn_index=0,
                type=MessageType.ASSISTANT,
                message_metadata={
                    "type": "agent_message",
                    "content": {"type": "text", "text": "built"},
                },
            )
        )
        db_session.commit()

        stub_sandbox_manager.supports_opencode_history_persistence = True
        stub_sandbox_manager.cleanup_session_workspace_silent = True

        deleted = session_manager_with_stub.delete_session(
            session_id=session_row.id, user_id=test_user.id
        )
        db_session.commit()

        assert deleted is True
        assert stub_sandbox_manager.delete_opencode_session_count == 0
        assert stub_sandbox_manager.create_opencode_history_snapshot_count == 0
        assert stub_sandbox_manager.cleanup_session_workspace_count == 1
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_row.id)
            .one_or_none()
            is None
        )

    def test_delete_session_allows_sleeping_established_session_without_opencode_id(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.SLEEPING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="sleeping-missing-opencode-id",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(session_row)
        db_session.flush()
        db_session.add_all(
            [
                BuildMessage(
                    session_id=session_row.id,
                    turn_index=0,
                    type=MessageType.USER,
                    message_metadata={
                        "type": "user_message",
                        "content": {"type": "text", "text": "one"},
                    },
                ),
                BuildMessage(
                    session_id=session_row.id,
                    turn_index=1,
                    type=MessageType.USER,
                    message_metadata={
                        "type": "user_message",
                        "content": {"type": "text", "text": "two"},
                    },
                ),
            ]
        )
        db_session.commit()

        stub_sandbox_manager.supports_opencode_history_persistence = True

        deleted = session_manager_with_stub.delete_session(
            session_id=session_row.id, user_id=test_user.id
        )
        db_session.commit()

        assert deleted is True
        assert stub_sandbox_manager.delete_opencode_session_count == 0
        assert stub_sandbox_manager.create_opencode_history_snapshot_count == 0
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_row.id)
            .one_or_none()
            is None
        )

    def test_delete_session_removes_s3_snapshots(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        # Regression for SHA 2c82f0da16. delete_session should drop both the
        # Snapshot DB row (ON DELETE CASCADE) and the underlying blob.
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="snap-owner",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(session_row)
        db_session.commit()
        session_id = session_row.id

        # Stash a real blob in the file store + a Snapshot row pointing at it.
        file_store = get_default_file_store()
        file_store.initialize()
        storage_path = file_store.save_file(
            content=io.BytesIO(b"snapshot-bytes"),
            display_name=f"snap-{session_id}.tar.gz",
            file_origin=FileOrigin.SANDBOX_SNAPSHOT,
            file_type="application/gzip",
        )
        snapshot = Snapshot(
            id=uuid4(),
            session_id=session_id,
            storage_path=storage_path,
            size_bytes=14,
        )
        db_session.add(snapshot)
        db_session.commit()
        snapshot_id = snapshot.id

        # Sanity: blob present, row present.
        assert file_store.has_file(
            storage_path,
            FileOrigin.SANDBOX_SNAPSHOT,
            "application/gzip",
        )

        stub_sandbox_manager.cleanup_session_workspace_silent = True
        sm = session_manager_with_stub
        deleted = sm.delete_session(session_id=session_id, user_id=test_user.id)
        db_session.commit()
        assert deleted is True

        # Snapshot row cascade-deleted.
        assert (
            db_session.query(Snapshot).filter(Snapshot.id == snapshot_id).one_or_none()
            is None
        )
        # And the blob was removed by SnapshotManager.delete_snapshot.
        assert not file_store.has_file(
            storage_path,
            FileOrigin.SANDBOX_SNAPSHOT,
            "application/gzip",
        )

    def test_delete_session_failure_to_clean_workspace_logged_not_raised(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session_row = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="cleanup-fails",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(session_row)
        db_session.commit()
        session_id = session_row.id

        # cleanup_session_workspace_silent left at False => stub will raise
        # NotImplementedError. The manager must log + swallow.
        stub_sandbox_manager.cleanup_session_workspace_silent = False

        sm = session_manager_with_stub
        with caplog.at_level(logging.WARNING):
            deleted = sm.delete_session(session_id=session_id, user_id=test_user.id)
            db_session.commit()
        assert deleted is True

        # DB delete actually happened.
        assert (
            db_session.query(BuildSession)
            .filter(BuildSession.id == session_id)
            .one_or_none()
            is None
        )

        # And a warning was emitted naming the failure.
        assert any(
            "Failed to cleanup session workspace" in r.getMessage()
            for r in caplog.records
        ), f"Expected cleanup warning; got: {[r.getMessage() for r in caplog.records]}"


# =============================================================================
# Port allocator
# =============================================================================


class TestPortAllocator:
    def test_nextjs_port_allocator_skips_unavailable(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Narrow the search range to [50000, 50004) so the test stays fast and
        # uses high ports unlikely to clash with anything on the test host.
        monkeypatch.setattr(
            "onyx.server.features.build.db.build_session.SANDBOX_NEXTJS_PORT_START",
            50000,
        )
        monkeypatch.setattr(
            "onyx.server.features.build.db.build_session.SANDBOX_NEXTJS_PORT_END",
            50004,
        )

        # Seed three BuildSessions occupying 50000/50001/50002.
        for port in (50000, 50001, 50002):
            db_session.add(
                BuildSession(
                    id=uuid4(),
                    user_id=test_user.id,
                    name=f"occupies-{port}",
                    status=BuildSessionStatus.ACTIVE,
                    nextjs_port=port,
                )
            )
        db_session.commit()

        allocated = allocate_nextjs_port(db_session)
        assert allocated == 50003

    def test_nextjs_port_allocator_raises_when_range_exhausted(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "onyx.server.features.build.db.build_session.SANDBOX_NEXTJS_PORT_START",
            50100,
        )
        monkeypatch.setattr(
            "onyx.server.features.build.db.build_session.SANDBOX_NEXTJS_PORT_END",
            50103,
        )

        for port in (50100, 50101, 50102):
            db_session.add(
                BuildSession(
                    id=uuid4(),
                    user_id=test_user.id,
                    name=f"taken-{port}",
                    status=BuildSessionStatus.ACTIVE,
                    nextjs_port=port,
                )
            )
        db_session.commit()

        with pytest.raises(OnyxError) as exc_info:
            allocate_nextjs_port(db_session)
        assert exc_info.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE


# =============================================================================
# Redis lock — concurrent create
# =============================================================================


class TestConcurrentCreateLock:
    def test_concurrent_create_serialized_by_redis_lock(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
    ) -> None:
        # Same lock contract as sessions_api.create_session: lock key is
        # ``session_create:{user_id}``. Two threads contend; the second
        # observes the first holding it.
        redis_client = get_redis_client(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        )
        lock_key = f"session_create:{test_user.id}"

        assert_lock_serializes_two_threads(redis_client, lock_key)


# =============================================================================
# Restore / sandbox reset
# =============================================================================


class TestRestoreSession:
    def test_restore_marks_session_active_from_idle(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,  # noqa: ARG002
        stub_sandbox_manager: StubSandboxManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Sandbox is RUNNING + healthy, session is IDLE, workspace already
        # exists in the pod. The documented IDLE -> ACTIVE transition in the
        # restore endpoint flips the row's status. Drive the real
        # ``restore_session`` handler from sessions_api so the assertion
        # exercises production code, not a hand-rolled stand-in.
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        idle_session = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="needs-restore",
            status=BuildSessionStatus.IDLE,
        )
        db_session.add(idle_session)
        db_session.commit()
        session_id = idle_session.id

        # Configure the stub for the "RUNNING + healthy + workspace_exists"
        # early-return branch in ``restore_session``. The `provision_returns`,
        # `setup_session_workspace_silent`, and `write_files_to_sandbox_silent`
        # knobs cover the SLEEPING / workspace-missing fallbacks so the test
        # is robust if the stub is consulted on any code path.
        stub_sandbox_manager.provision_returns = SandboxInfo(
            sandbox_id=uuid4(),
            directory_path="/tmp/sandbox",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )
        stub_sandbox_manager.health_check_returns = True
        stub_sandbox_manager.session_workspace_exists_returns = True
        stub_sandbox_manager.setup_session_workspace_silent = True
        stub_sandbox_manager.write_files_to_sandbox_silent = True

        # Patch the import site used by ``restore_session``.
        monkeypatch.setattr(
            "onyx.server.features.build.session.api.get_sandbox_manager",
            lambda: stub_sandbox_manager,
        )

        restore_session(
            session_id=session_id,
            user=test_user,
            db_session=db_session,
        )

        db_session.refresh(idle_session)
        assert idle_session.status == BuildSessionStatus.ACTIVE

    def test_sleeping_sandbox_restore_provisions_and_restores_latest_snapshot(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,  # noqa: ARG002
        stub_sandbox_manager: StubSandboxManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sandbox_row = sandbox(user=test_user, status=SandboxStatus.SLEEPING)
        idle_session = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="sleeping-restore",
            status=BuildSessionStatus.IDLE,
        )
        db_session.add(idle_session)
        db_session.flush()
        snapshot = Snapshot(
            id=uuid4(),
            session_id=idle_session.id,
            storage_path=f"{POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE}/snapshots/{idle_session.id}/latest.tar.gz",
            size_bytes=123,
        )
        db_session.add(snapshot)
        db_session.commit()

        stub_sandbox_manager.provision_returns = SandboxInfo(
            sandbox_id=sandbox_row.id,
            directory_path="/tmp/sandbox",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )
        stub_sandbox_manager.session_workspace_exists_returns = False
        stub_sandbox_manager.restore_snapshot_silent = True
        stub_sandbox_manager.write_files_to_sandbox_silent = True

        monkeypatch.setattr(
            "onyx.server.features.build.session.api.get_sandbox_manager",
            lambda: stub_sandbox_manager,
        )

        restore_session(
            session_id=idle_session.id,
            user=test_user,
            db_session=db_session,
        )

        db_session.expire_all()
        refreshed_sandbox = db_session.get(Sandbox, sandbox_row.id)
        refreshed_session = db_session.get(BuildSession, idle_session.id)
        assert refreshed_sandbox is not None
        assert refreshed_sandbox.status == SandboxStatus.RUNNING
        assert refreshed_session is not None
        assert refreshed_session.status == BuildSessionStatus.ACTIVE
        assert refreshed_session.nextjs_port is not None
        assert stub_sandbox_manager.last_restore_snapshot_payload is not None
        assert stub_sandbox_manager.last_restore_snapshot_payload["sandbox_id"] == (
            sandbox_row.id
        )
        assert stub_sandbox_manager.last_restore_snapshot_payload["session_id"] == (
            idle_session.id
        )
        assert (
            stub_sandbox_manager.last_restore_snapshot_payload["snapshot_storage_path"]
            == snapshot.storage_path
        )
        assert stub_sandbox_manager.last_write_files_to_sandbox_payload is not None
        assert (
            stub_sandbox_manager.last_write_files_to_sandbox_payload["mount_path"]
            == USER_LIBRARY_MOUNT_PATH
        )

    def test_restore_preserves_port_exhaustion_onyx_error(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,  # noqa: ARG002
        stub_sandbox_manager: StubSandboxManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        idle_session = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="restore-port-exhausted",
            status=BuildSessionStatus.IDLE,
            nextjs_port=None,
        )
        db_session.add(idle_session)
        db_session.commit()

        stub_sandbox_manager.health_check_returns = True
        stub_sandbox_manager.session_workspace_exists_returns = False

        monkeypatch.setattr(
            "onyx.server.features.build.session.api.get_sandbox_manager",
            lambda: stub_sandbox_manager,
        )

        def _raise_port_exhausted(_db_session: Session) -> int:
            raise OnyxError(
                OnyxErrorCode.SERVICE_UNAVAILABLE,
                "No available ports in configured range",
            )

        monkeypatch.setattr(
            "onyx.server.features.build.session.api.allocate_nextjs_port",
            _raise_port_exhausted,
        )

        with pytest.raises(OnyxError) as exc_info:
            restore_session(
                session_id=idle_session.id,
                user=test_user,
                db_session=db_session,
            )

        assert exc_info.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE


# =============================================================================
# Sidebar listing — SCHEDULED-origin filter
# =============================================================================


class TestSidebarOriginFilter:
    def test_scheduled_origin_session_excluded_from_sidebar_listing(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """``get_user_build_sessions`` filters out ``origin=SCHEDULED`` rows.

        Relocated from ``backend/tests/integration/tests/craft/
        test_scheduled_tasks_api.py`` — the original test inserted
        ``BuildSession`` + ``BuildMessage`` rows directly via
        ``get_session_with_current_tenant``, which is an
        ext-dep-shaped assertion (DB row visibility through the query
        function), not an HTTP-shaped one. The sidebar listing's HTTP
        boundary is covered separately by the GET /api/build/sessions
        integration tests; this test pins the DB query predicate.

        The covering composite index
        ``ix_build_session_user_origin_created`` is built for this exact
        ``(user_id, origin, created_at DESC)`` shape — a regression here
        would silently leak scheduled-task fire sessions into the Craft
        sidebar.
        """
        # Both sessions need a BuildMessage row because
        # ``get_user_build_sessions`` requires ``EXISTS messages`` —
        # without one, BOTH origin types would be filtered and we'd have
        # nothing to compare against.
        interactive = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="interactive",
            status=BuildSessionStatus.ACTIVE,
            origin=SessionOrigin.INTERACTIVE,
        )
        scheduled = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="scheduled-run",
            status=BuildSessionStatus.ACTIVE,
            origin=SessionOrigin.SCHEDULED,
        )
        db_session.add_all([interactive, scheduled])
        db_session.flush()
        db_session.add_all(
            [
                BuildMessage(
                    session_id=interactive.id,
                    turn_index=0,
                    type=MessageType.USER,
                    message_metadata={
                        "type": "user_message",
                        "content": {"text": "hi"},
                    },
                ),
                BuildMessage(
                    session_id=scheduled.id,
                    turn_index=0,
                    type=MessageType.USER,
                    message_metadata={
                        "type": "user_message",
                        "content": {"text": "fire"},
                    },
                ),
            ]
        )
        db_session.commit()

        listed = get_user_build_sessions(test_user.id, db_session)
        listed_ids = {s.id for s in listed}

        # Observable outcome: the SCHEDULED row is invisible to the
        # sidebar query while the INTERACTIVE row is visible.
        assert interactive.id in listed_ids
        assert scheduled.id not in listed_ids
