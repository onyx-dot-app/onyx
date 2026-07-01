"""Sandbox lifecycle (status state machine), DB-only half.

DB-bound tests that pin the sandbox state machine: PROVISIONING → RUNNING,
provision failures rolling back the row, idempotent provisioning, the
health-check failure -> re-provision recovery path, and the idle-selection
query shape.

The full ``cleanup_idle_sandboxes_task`` end-to-end behavior lives in
``test_idle_cleanup.py`` — this file only covers the selection query, not
the task body.
"""

from __future__ import annotations

import datetime
from typing import Callable
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.build.tasks import is_sandbox_idle
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import create_snapshot__no_commit
from onyx.server.features.build.db.sandbox import get_running_sandboxes
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.session.api import restore_session
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.sandbox_lifecycle import provision_sandbox
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.common.craft.payloads import default_llm_config
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_sandbox
from tests.external_dependency_unit.craft.db_helpers import make_user


class TestProvisionTransitions:
    def test_provision_transitions_provisioning_to_running(
        self,
        db_session: Session,
        test_user: User,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        # Create a sandbox row in PROVISIONING (the state set by
        # create_sandbox__no_commit before provision_sandbox is called).
        sandbox = create_sandbox__no_commit(db_session, test_user.id)
        db_session.commit()
        assert sandbox.status == SandboxStatus.PROVISIONING

        # Stub returns RUNNING from provision().
        stub_sandbox_manager.provision_returns = SandboxInfo(
            sandbox_id=sandbox.id,
            directory_path="/tmp/sandbox",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )

        provision_sandbox(
            db_session=db_session,
            sandbox_manager=stub_sandbox_manager,
            sandbox=sandbox,
            user=test_user,
            user_id=test_user.id,
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            all_llm_configs=[default_llm_config()],
        )
        db_session.commit()
        db_session.refresh(sandbox)

        # Observable outcome: the DB row reflects the new state. We deliberately
        # do NOT assert on ``provision_count`` — that's a mechanism assertion
        # (P1) and ``StubSandboxManager.provision`` already raises if called
        # without ``provision_returns`` set, which itself proves the call ran.
        assert sandbox.status == SandboxStatus.RUNNING


class TestProvisionFailureRollback:
    def test_provision_failure_rolls_back_db(
        self,
        db_session: Session,
        test_user: User,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        # Mirror the endpoint pattern: create_sandbox__no_commit (flush only),
        # then call provision_sandbox; if it raises, the caller rolls back so
        # no Sandbox row persists.
        sandbox = create_sandbox__no_commit(db_session, test_user.id)
        sandbox_id = sandbox.id
        # No provision_returns => stub raises NotImplementedError on provision().

        with pytest.raises(NotImplementedError):
            provision_sandbox(
                db_session=db_session,
                sandbox_manager=stub_sandbox_manager,
                sandbox=sandbox,
                user=test_user,
                user_id=test_user.id,
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                all_llm_configs=[default_llm_config()],
            )

        # The endpoint's exception handler rolls back. Simulate that here.
        db_session.rollback()

        # No row persisted at the (pre-flush, uncommitted) sandbox id.
        assert (
            db_session.query(Sandbox).filter(Sandbox.id == sandbox_id).one_or_none()
            is None
        )


class TestIdempotentProvision:
    def test_idempotent_provision_reuses_running_sandbox(
        self,
        db_session: Session,
        test_user: User,
        stub_sandbox_manager: StubSandboxManager,
        session_manager_with_stub: SessionManager,
    ) -> None:
        # Drive the real ``SessionManager.create_session__no_commit`` twice
        # and assert the second call observes the existing sandbox row
        # instead of provisioning a new one. ``provision_returns`` is
        # intentionally cleared between calls — the stub will raise if
        # ``provision`` is invoked on the second pass, which would surface
        # as a test failure.
        stub_sandbox_manager.provision_returns = SandboxInfo(
            sandbox_id=uuid4(),
            directory_path="/tmp/sandbox",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )
        stub_sandbox_manager.health_check_returns = True
        stub_sandbox_manager.setup_session_workspace_silent = True
        stub_sandbox_manager.write_files_to_sandbox_silent = True

        # First call: provisions a new sandbox row.
        session_manager_with_stub.create_session__no_commit(user_id=test_user.id)
        db_session.commit()

        first_rows = (
            db_session.query(Sandbox).filter(Sandbox.user_id == test_user.id).all()
        )
        assert len(first_rows) == 1
        first_sandbox_id = first_rows[0].id
        assert first_rows[0].status == SandboxStatus.RUNNING

        # Clear ``provision_returns`` so the stub raises if a second
        # provision is attempted (observable proof of non-idempotence).
        stub_sandbox_manager.provision_returns = None

        # Second call: same user. Should reuse the existing sandbox row
        # via the health-check branch and never call ``provision``.
        session_manager_with_stub.create_session__no_commit(user_id=test_user.id)
        db_session.commit()

        rows = db_session.query(Sandbox).filter(Sandbox.user_id == test_user.id).all()
        # Observable outcome: exactly one sandbox row for this user, and
        # it is the original one — not a freshly-provisioned replacement.
        assert len(rows) == 1
        assert rows[0].id == first_sandbox_id
        assert rows[0].status == SandboxStatus.RUNNING


class TestHealthCheckFailureRecovery:
    @pytest.mark.parametrize(
        "history_snapshot_fails",
        [
            pytest.param(False, id="history-snapshot-succeeds"),
            pytest.param(True, id="history-snapshot-fails"),
        ],
    )
    def test_health_check_failure_snapshots_history_best_effort_then_reprovisions(
        self,
        history_snapshot_fails: bool,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        stub_sandbox_manager: StubSandboxManager,
        session_manager_with_stub: SessionManager,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Sandbox is RUNNING in the DB but the pod is unhealthy. Drive the
        # real ``restore_session`` HTTP handler: its recovery branch
        # (sessions_api.py:411-460) terminates the pod, marks the row
        # TERMINATED, re-provisions, and flips back to RUNNING.
        row = sandbox(user=test_user, status=SandboxStatus.RUNNING)

        # Seed an IDLE session for the user — restore_session needs a
        # BuildSession row to operate on, and the recovery path is gated
        # on a session_id argument.
        idle_session = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="needs-recovery",
            status=BuildSessionStatus.IDLE,
        )
        db_session.add(idle_session)
        db_session.commit()
        session_id = idle_session.id

        stub_sandbox_manager.health_check_returns = False
        stub_sandbox_manager.supports_opencode_history_persistence = True
        if history_snapshot_fails:

            def _boom(
                sandbox_id: object,
                tenant_id: object,
                timeout_seconds: float = 300.0,
            ) -> bool:
                stub_sandbox_manager.create_opencode_history_snapshot_payloads.append(
                    {
                        "sandbox_id": sandbox_id,
                        "tenant_id": tenant_id,
                        "timeout_seconds": timeout_seconds,
                    }
                )
                raise RuntimeError("history snapshot failed")

            monkeypatch.setattr(
                stub_sandbox_manager, "create_opencode_history_snapshot", _boom
            )
        else:
            stub_sandbox_manager.create_opencode_history_snapshot_returns = True
        stub_sandbox_manager.terminate_silent = True
        stub_sandbox_manager.provision_returns = SandboxInfo(
            sandbox_id=row.id,
            directory_path="/tmp/sandbox",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )
        # After the recovery re-provision, the workspace is missing, so
        # restore_session falls through to setup_session_workspace.
        stub_sandbox_manager.session_workspace_exists_returns = False
        stub_sandbox_manager.setup_session_workspace_silent = True
        stub_sandbox_manager.write_files_to_sandbox_silent = True

        # restore_session reads ``get_sandbox_manager`` from sessions_api.
        monkeypatch.setattr(
            "onyx.server.features.build.session.api.get_sandbox_manager",
            lambda: stub_sandbox_manager,
        )

        restore_session(
            session_id=session_id,
            user=test_user,
            db_session=db_session,
        )

        db_session.expire_all()
        refreshed = db_session.get(Sandbox, row.id)
        # Observable outcome: row landed at RUNNING after the recovery
        # cycle (TERMINATED -> PROVISIONING -> RUNNING).
        assert refreshed is not None
        assert refreshed.status == SandboxStatus.RUNNING
        assert {
            "sandbox_id": row.id,
            "tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            "timeout_seconds": 30.0,
        } in stub_sandbox_manager.create_opencode_history_snapshot_payloads


class TestRestoreFailureRecovery:
    def test_workspace_load_failure_cleans_up_partial_workspace(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        stub_sandbox_manager: StubSandboxManager,
        session_manager_with_stub: SessionManager,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # provision() succeeds (the row flips SLEEPING -> RUNNING and commits),
        # but loading the session workspace then fails. The recovery branch
        # must leave the healthy pod RUNNING and remove the half-written
        # workspace so the next attempt redoes the load cleanly — otherwise
        # session_workspace_exists() returns True for the partial dir and the
        # session is falsely reported as restored.
        row = sandbox(user=test_user, status=SandboxStatus.SLEEPING)

        idle_session = BuildSession(
            id=uuid4(),
            user_id=test_user.id,
            name="restore-fails",
            status=BuildSessionStatus.IDLE,
        )
        db_session.add(idle_session)
        db_session.commit()
        session_id = idle_session.id

        # A snapshot exists, so restore takes the restore_snapshot branch.
        create_snapshot__no_commit(
            db_session,
            session_id,
            f"{POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE}/snapshots/{session_id}/snap.tar.gz",
            size_bytes=123,
        )
        db_session.commit()

        stub_sandbox_manager.provision_returns = SandboxInfo(
            sandbox_id=row.id,
            directory_path="/tmp/sandbox",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )
        stub_sandbox_manager.session_workspace_exists_returns = False
        # restore_snapshot left unconfigured -> raises, simulating a failed
        # workspace load after a successful provision.
        stub_sandbox_manager.cleanup_session_workspace_silent = True

        monkeypatch.setattr(
            "onyx.server.features.build.session.api.get_sandbox_manager",
            lambda: stub_sandbox_manager,
        )

        with pytest.raises(HTTPException) as exc_info:
            restore_session(
                session_id=session_id,
                user=test_user,
                db_session=db_session,
            )
        assert exc_info.value.status_code == 500

        # The partial workspace was cleaned up for this exact session...
        assert stub_sandbox_manager.cleanup_session_workspace_count == 1
        assert stub_sandbox_manager.last_cleanup_session_workspace_payload is not None
        assert (
            stub_sandbox_manager.last_cleanup_session_workspace_payload["session_id"]
            == session_id
        )

        # ...and the healthy pod stays RUNNING (no needless re-provision).
        db_session.expire_all()
        refreshed = db_session.get(Sandbox, row.id)
        assert refreshed is not None
        assert refreshed.status == SandboxStatus.RUNNING


class TestListArtifacts:
    def _seed_session(self, db_session: Session, user: User) -> BuildSession:
        session = BuildSession(
            id=uuid4(),
            user_id=user.id,
            name="artifacts",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(session)
        db_session.commit()
        return session

    def test_transient_sandbox_error_degrades_to_empty(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        stub_sandbox_manager: StubSandboxManager,
        session_manager_with_stub: SessionManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # list_directory reaches into the sandbox and can fail transiently
        # while the pod is still coming up after a restore. list_artifacts must
        # degrade to [] (200) rather than propagating a 500.
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session = self._seed_session(db_session, test_user)

        def _raise_transient(**_kwargs: object) -> list[FilesystemEntry]:
            raise RuntimeError("Failed to list directory: pod not ready")

        monkeypatch.setattr(stub_sandbox_manager, "list_directory", _raise_transient)

        result = session_manager_with_stub.list_artifacts(session.id, test_user.id)

        assert result == []

    def test_lists_webapp_when_sandbox_reachable(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        stub_sandbox_manager: StubSandboxManager,
        session_manager_with_stub: SessionManager,
    ) -> None:
        # Sanity: when the sandbox is reachable and outputs/web exists, the
        # web_app artifact is still surfaced (no regression from the new guard).
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        session = self._seed_session(db_session, test_user)

        stub_sandbox_manager.list_directory_returns = [
            FilesystemEntry(name="web", path="outputs/web", is_directory=True),
        ]

        result = session_manager_with_stub.list_artifacts(session.id, test_user.id)

        assert result is not None
        assert [a["type"] for a in result] == ["web_app"]


class TestIdleCleanupSelection:
    def test_idle_cleanup_with_null_heartbeat_past_created_at_is_included(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        # Regression for SHA eba89fa635: RUNNING sandboxes with NULL heartbeat
        # whose created_at is past the threshold should be considered idle.
        user = make_user(db_session)
        row = make_sandbox(db_session, user, status=SandboxStatus.RUNNING)
        row.last_heartbeat = None
        row.created_at = datetime.datetime.now(
            datetime.timezone.utc
        ) - datetime.timedelta(hours=2)
        db_session.commit()

        now = datetime.datetime.now(datetime.timezone.utc)
        idle_ids = {
            s.id for s in get_running_sandboxes(db_session) if is_sandbox_idle(s, now)
        }
        assert row.id in idle_ids

    def test_idle_cleanup_excludes_sandbox_within_threshold(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        # heartbeat 30 minutes ago + 1 hour threshold => not selected.
        user = make_user(db_session)
        row = make_sandbox(db_session, user, status=SandboxStatus.RUNNING)
        row.last_heartbeat = datetime.datetime.now(
            datetime.timezone.utc
        ) - datetime.timedelta(minutes=30)
        db_session.commit()

        now = datetime.datetime.now(datetime.timezone.utc)
        idle_ids = {
            s.id for s in get_running_sandboxes(db_session) if is_sandbox_idle(s, now)
        }
        assert row.id not in idle_ids
