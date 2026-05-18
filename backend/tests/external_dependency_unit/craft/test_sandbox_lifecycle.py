"""Sandbox lifecycle (status state machine), DB-only half.

DB-bound tests that pin the sandbox state machine: PROVISIONING → RUNNING,
provision failures rolling back the row, idempotent provisioning, the
health-check failure -> re-provision recovery path, the ``get_idle_sandboxes``
query shape, and the Redis lock that serializes concurrent provision
attempts for the same user.

The full ``cleanup_idle_sandboxes_task`` end-to-end behavior lives in
``test_idle_cleanup.py`` — this file only covers the selection query, not
the task body.
"""

from __future__ import annotations

import datetime
from typing import Callable
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.build.api.sessions_api import restore_session
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import get_idle_sandboxes
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.session.manager import SessionManager
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import default_llm_config
from tests.external_dependency_unit.craft._test_helpers import make_sandbox
from tests.external_dependency_unit.craft._test_helpers import make_user
from tests.external_dependency_unit.craft.conftest import (
    assert_lock_serializes_two_threads,
)
from tests.external_dependency_unit.craft.stubs import StubSandboxManager


class TestProvisionTransitions:
    def test_provision_transitions_provisioning_to_running(
        self,
        db_session: Session,
        test_user: User,
        stub_sandbox_manager: StubSandboxManager,
        session_manager_with_stub: SessionManager,
    ) -> None:
        # Create a sandbox row in PROVISIONING (the state set by
        # create_sandbox__no_commit before _provision_sandbox is called).
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

        session_manager_with_stub._provision_sandbox(
            sandbox=sandbox,
            user=test_user,
            user_id=test_user.id,
            tenant_id=TEST_TENANT_ID,
            llm_config=default_llm_config(),
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
        session_manager_with_stub: SessionManager,
    ) -> None:
        # Mirror the endpoint pattern: create_sandbox__no_commit (flush only),
        # then call _provision_sandbox; if it raises, the caller rolls back so
        # no Sandbox row persists.
        sandbox = create_sandbox__no_commit(db_session, test_user.id)
        sandbox_id = sandbox.id
        # No provision_returns => stub raises NotImplementedError on provision().

        with pytest.raises(NotImplementedError):
            session_manager_with_stub._provision_sandbox(
                sandbox=sandbox,
                user=test_user,
                user_id=test_user.id,
                tenant_id=TEST_TENANT_ID,
                llm_config=default_llm_config(),
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
    def test_health_check_failure_marks_terminated_and_reprovisions(
        self,
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
            "onyx.server.features.build.api.sessions_api.get_sandbox_manager",
            lambda: stub_sandbox_manager,
        )
        # Bypass LLM provider lookup (no real provider in ext-dep CI).
        monkeypatch.setattr(
            "onyx.server.features.build.session.manager.SessionManager._get_llm_config",
            lambda _self, *_a, **_kw: default_llm_config(),
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

        idle = get_idle_sandboxes(db_session, idle_threshold_seconds=3600)

        idle_ids = {s.id for s in idle}
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

        idle = get_idle_sandboxes(db_session, idle_threshold_seconds=3600)

        assert row.id not in {s.id for s in idle}


# NOTE: ``test_idle_cleanup_marks_sandbox_sleeping_and_sessions_idle`` was
# removed here. It hand-rolled the post-snapshot half of
# ``cleanup_idle_sandboxes_task`` (clear_nextjs_ports_for_user +
# mark_user_sessions_idle__no_commit + update_sandbox_status__no_commit) in
# the test body, which is a P1 violation: the test was reimplementing
# production logic rather than asserting an observable outcome of the real
# task. The same end-state is covered by
# ``backend/tests/external_dependency_unit/craft/test_idle_cleanup.py:
# test_sessions_marked_idle_and_nextjs_ports_cleared``, which invokes
# ``cleanup_idle_sandboxes_task.run`` directly and asserts the IDLE flip
# plus cleared ``nextjs_port`` on every active session for the user.


class TestConcurrentProvisionLock:
    def test_concurrent_provision_serialized_by_redis_lock(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
    ) -> None:
        # Real Redis lock under the same key shape used by sessions_api.py
        # (``session_create:{user_id}``). Two threads race for the lock; the
        # second observes that the first held it and therefore had to wait.
        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        lock_key = f"session_create:{test_user.id}"

        assert_lock_serializes_two_threads(redis_client, lock_key)
