"""Durable provisioning lifecycle: reserve → reconcile → finalize.

Pins the transaction-ordering contract with real PostgreSQL and a controlled
sandbox-manager double:

* the sandbox identity, owner, PAT, and attempt number are committed — and
  visible to an independent database connection — before the first external
  provisioning call, with no transaction left open on the flow's session;
* a simulated process death mid-provision leaves resumable committed state
  that a retry converges on (same sandbox ID, new attempt number);
* a death mid-session-initialization is repaired under the same session ID;
* a superseded attempt cannot finalize over a newer one;
* session initialization failure marks only the session FAILED while the
  sandbox stays RUNNING;
* concurrent creators converge on one sandbox and one empty session.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.auth.pat import hash_pat
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import BuildSessionStatus, Permission, SandboxStatus
from onyx.db.models import BuildSession, PersonalAccessToken, Sandbox, User
from onyx.server.features.build.db.sandbox import (
    begin_provisioning_attempt__no_commit,
    finalize_provisioning_attempt__no_commit,
    get_sandbox_by_user_id,
)
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.session.errors import (
    SandboxProvisioningError,
    SandboxProvisioningInProgressError,
    StaleProvisioningAttemptError,
)
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.sandbox_lifecycle import (
    ProvisioningPolicy,
    ensure_sandbox_ready,
)
from onyx.utils.threadpool_concurrency import start_thread_with_context
from tests.common.craft.stubs import StubSandboxManager


class _SimulatedProcessDeath(BaseException):
    """Escapes the ``except Exception`` failure recording, mimicking an API
    process dying mid-call (no FAILED transition is written)."""


def _running_info(sandbox_id: UUID) -> SandboxInfo:
    return SandboxInfo(
        sandbox_id=sandbox_id,
        directory_path="/tmp/sandbox",
        status=SandboxStatus.RUNNING,
        last_heartbeat=None,
    )


@dataclass
class _ReservationProbe:
    """What an independent database connection could see mid-provision."""

    flow_session_in_transaction: bool
    sandbox_visible: bool = False
    owner_user_id: UUID | None = None
    status: SandboxStatus | None = None
    attempt_number: int | None = None
    pat_present: bool = False
    pat_row_valid: bool = False


class _ProbingStub(StubSandboxManager):
    """On ``provision``, inspects committed state through an independent
    database connection and records what it could see."""

    def __init__(self, flow_db_session: Session) -> None:
        super().__init__()
        self._flow_db_session = flow_db_session
        self.probe: _ReservationProbe | None = None

    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        onyx_pat: str | None,
        provisioning_attempt_number: int,
    ) -> SandboxInfo:
        probe = _ReservationProbe(
            flow_session_in_transaction=self._flow_db_session.in_transaction(),
        )
        with get_session_with_current_tenant() as probe_session:
            row = (
                probe_session.query(Sandbox)
                .filter(Sandbox.id == sandbox_id)
                .one_or_none()
            )
            probe.sandbox_visible = row is not None
            if row is not None:
                probe.owner_user_id = row.user_id
                probe.status = row.status
                probe.attempt_number = row.provisioning_attempt_number
                raw_pat = (
                    row.encrypted_pat.get_value(apply_mask=False)
                    if row.encrypted_pat
                    else None
                )
                probe.pat_present = raw_pat is not None
                if raw_pat is not None:
                    pat_row = (
                        probe_session.query(PersonalAccessToken)
                        .filter(PersonalAccessToken.hashed_token == hash_pat(raw_pat))
                        .one_or_none()
                    )
                    probe.pat_row_valid = (
                        pat_row is not None
                        and pat_row.user_id == user_id
                        and pat_row.scopes == [Permission.CRAFT_SANDBOX.value]
                    )
        self.probe = probe
        return super().provision(
            sandbox_id,
            user_id,
            tenant_id,
            onyx_pat=onyx_pat,
            provisioning_attempt_number=provisioning_attempt_number,
        )


def test_reservation_committed_and_visible_before_first_external_call(
    db_session: Session,
    test_user: User,
    session_manager_with_stub: SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _ProbingStub(db_session)
    stub.provision_returns = _running_info(uuid4())
    stub.setup_session_workspace_silent = True
    stub.write_files_to_sandbox_silent = True
    stub.write_sandbox_file_silent = True
    monkeypatch.setattr(session_manager_with_stub, "_sandbox_manager", stub)

    session_manager_with_stub.get_or_create_empty_session(user_id=test_user.id)

    assert stub.probe is not None
    # The bootstrap identity was durable before the pod existed: another
    # connection resolves the owner and validates the PAT (exactly what the
    # egress proxy does for npm bootstrap), while the flow's own session
    # holds no open transaction across the external call.
    assert stub.probe.sandbox_visible is True
    assert stub.probe.owner_user_id == test_user.id
    assert stub.probe.status == SandboxStatus.PROVISIONING
    assert stub.probe.attempt_number == 1
    assert stub.probe.pat_present is True
    assert stub.probe.pat_row_valid is True
    assert stub.probe.flow_session_in_transaction is False


def test_interrupted_provision_resumes_same_sandbox_identity(
    db_session: Session,
    test_user: User,
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    def _die(*_args: object, **_kwargs: object) -> SandboxInfo:
        raise _SimulatedProcessDeath()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stub_sandbox_manager, "provision", _die)
        with pytest.raises(_SimulatedProcessDeath):
            session_manager_with_stub.get_or_create_empty_session(user_id=test_user.id)

        db_session.rollback()
        interrupted = get_sandbox_by_user_id(db_session, test_user.id)
        assert interrupted is not None
        interrupted_id = interrupted.id
        # Process death leaves the committed reservation, not FAILED.
        assert interrupted.status == SandboxStatus.PROVISIONING
        assert interrupted.provisioning_attempt_number == 1

        # A live attempt is not taken over.
        with pytest.raises(SandboxProvisioningInProgressError):
            session_manager_with_stub.get_or_create_empty_session(user_id=test_user.id)

    # Once the attempt is stale, a retry resumes the same identity under a
    # new attempt number.
    db_session.rollback()
    interrupted.provisioning_started_at = datetime.now(timezone.utc) - timedelta(
        minutes=10
    )
    db_session.commit()
    stub_sandbox_manager.provision_returns = _running_info(interrupted_id)
    stub_sandbox_manager.setup_session_workspace_silent = True
    stub_sandbox_manager.write_files_to_sandbox_silent = True
    stub_sandbox_manager.write_sandbox_file_silent = True
    # Taking over a stale PROVISIONING attempt tears down its half-built
    # runtime before re-provisioning.
    stub_sandbox_manager.terminate_silent = True
    # The reused empty session takes the workspace-missing repair path.
    stub_sandbox_manager.session_workspace_exists_returns = False

    result = session_manager_with_stub.get_or_create_empty_session(user_id=test_user.id)

    rows = db_session.query(Sandbox).filter(Sandbox.user_id == test_user.id).all()
    assert len(rows) == 1
    assert rows[0].id == interrupted_id
    assert rows[0].status == SandboxStatus.RUNNING
    assert rows[0].provisioning_attempt_number == 2
    db_session.refresh(result)
    assert result.status == BuildSessionStatus.ACTIVE


def test_interrupted_session_initialization_repaired_under_same_id(
    db_session: Session,
    test_user: User,
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    stub_sandbox_manager.provision_returns = _running_info(uuid4())
    stub_sandbox_manager.write_files_to_sandbox_silent = True
    stub_sandbox_manager.write_sandbox_file_silent = True
    stub_sandbox_manager.health_check_returns = True

    def _die(*_args: object, **_kwargs: object) -> None:
        raise _SimulatedProcessDeath()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stub_sandbox_manager, "setup_session_workspace", _die)
        with pytest.raises(_SimulatedProcessDeath):
            session_manager_with_stub.get_or_create_empty_session(user_id=test_user.id)

    db_session.rollback()
    reserved = (
        db_session.query(BuildSession)
        .filter(BuildSession.user_id == test_user.id)
        .one()
    )
    # Death mid-initialization leaves the committed INITIALIZING identity
    # (BaseException bypasses the FAILED recording, like a process crash).
    assert reserved.status == BuildSessionStatus.INITIALIZING
    reserved_id = reserved.id
    reserved_port = reserved.nextjs_port
    assert reserved_port is not None

    stub_sandbox_manager.setup_session_workspace_silent = True
    stub_sandbox_manager.session_workspace_exists_returns = False

    repaired = session_manager_with_stub.get_or_create_empty_session(
        user_id=test_user.id
    )

    # Same committed session identity and port, now finalized ACTIVE.
    assert repaired.id == reserved_id
    db_session.refresh(repaired)
    assert repaired.status == BuildSessionStatus.ACTIVE
    assert repaired.nextjs_port == reserved_port
    rows = (
        db_session.query(BuildSession)
        .filter(BuildSession.user_id == test_user.id)
        .all()
    )
    assert len(rows) == 1


def test_attempt_self_deadline_finalizes_failed_before_external_work(
    db_session: Session,
    test_user: User,
    stub_sandbox_manager: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An attempt past ``ATTEMPT_DEADLINE_SECONDS`` aborts itself, recording
    FAILED durably without ever reaching ``provision()`` — the same number
    observers use to declare the attempt stale."""
    monkeypatch.setattr(
        "onyx.server.features.build.session.sandbox_lifecycle.ATTEMPT_DEADLINE_SECONDS",
        -1.0,
    )

    with pytest.raises(SandboxProvisioningError):
        ensure_sandbox_ready(
            db_session,
            stub_sandbox_manager,
            test_user.id,
            policy=ProvisioningPolicy.FAIL,
        )

    db_session.rollback()
    sandbox = get_sandbox_by_user_id(db_session, test_user.id)
    assert sandbox is not None
    assert sandbox.status == SandboxStatus.FAILED
    assert stub_sandbox_manager.provision_count == 0


def test_stale_generation_cannot_finalize_newer_generation(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
) -> None:
    row = sandbox(user=test_user, status=SandboxStatus.SLEEPING)
    stale_attempt_number = begin_provisioning_attempt__no_commit(db_session, row)
    db_session.commit()

    # A newer reservation takes over (e.g. the first attempt went stale).
    newer_attempt_number = begin_provisioning_attempt__no_commit(db_session, row)
    db_session.commit()
    assert newer_attempt_number == stale_attempt_number + 1

    # The stale attempt's finalize must be a no-op.
    assert not finalize_provisioning_attempt__no_commit(
        db_session, row.id, stale_attempt_number, SandboxStatus.RUNNING
    )
    db_session.commit()
    db_session.refresh(row)
    assert row.status == SandboxStatus.PROVISIONING
    assert row.provisioning_attempt_number == newer_attempt_number

    # The current attempt finalizes normally.
    assert finalize_provisioning_attempt__no_commit(
        db_session, row.id, newer_attempt_number, SandboxStatus.RUNNING
    )
    db_session.commit()
    db_session.refresh(row)
    assert row.status == SandboxStatus.RUNNING


def test_session_failure_leaves_sandbox_running_session_failed(
    db_session: Session,
    test_user: User,
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    stub_sandbox_manager.provision_returns = _running_info(uuid4())
    stub_sandbox_manager.write_files_to_sandbox_silent = True
    stub_sandbox_manager.write_sandbox_file_silent = True
    # setup_session_workspace left unconfigured => raises on call.

    with pytest.raises(RuntimeError):
        session_manager_with_stub.get_or_create_empty_session(user_id=test_user.id)

    db_session.rollback()
    sandbox_row = get_sandbox_by_user_id(db_session, test_user.id)
    session_row = (
        db_session.query(BuildSession)
        .filter(BuildSession.user_id == test_user.id)
        .one()
    )
    # Sandbox readiness and session readiness are separate: the healthy
    # sandbox stays RUNNING while only the session records the failure.
    assert sandbox_row is not None
    assert sandbox_row.status == SandboxStatus.RUNNING
    assert session_row.status == BuildSessionStatus.FAILED
    failed_id = session_row.id

    # Retry repairs the same session ID.
    stub_sandbox_manager.health_check_returns = True
    stub_sandbox_manager.session_workspace_exists_returns = False
    stub_sandbox_manager.setup_session_workspace_silent = True

    repaired = session_manager_with_stub.get_or_create_empty_session(
        user_id=test_user.id
    )
    assert repaired.id == failed_id
    db_session.refresh(repaired)
    assert repaired.status == BuildSessionStatus.ACTIVE


def test_concurrent_creators_converge_on_one_sandbox_and_session(
    db_session: Session,
    test_user: User,
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,  # noqa: ARG001 — patches the factory
) -> None:
    stub_sandbox_manager.provision_returns = _running_info(uuid4())
    stub_sandbox_manager.health_check_returns = True
    stub_sandbox_manager.session_workspace_exists_returns = True
    stub_sandbox_manager.setup_session_workspace_silent = True
    stub_sandbox_manager.write_files_to_sandbox_silent = True
    stub_sandbox_manager.write_sandbox_file_silent = True
    stub_sandbox_manager.read_file_returns = b"{}"
    stub_sandbox_manager.regenerate_session_config_silent = True
    stub_sandbox_manager.dispose_opencode_instance_silent = True

    results: list[UUID] = []
    errors: list[BaseException] = []

    def _create() -> None:
        try:
            with get_session_with_current_tenant() as thread_session:
                manager = SessionManager(thread_session)
                manager._sandbox_manager = stub_sandbox_manager
                created = manager.get_or_create_empty_session(user_id=test_user.id)
                results.append(created.id)
        except BaseException as e:  # noqa: BLE001 — collected for assertions
            errors.append(e)

    threads = [start_thread_with_context(_create) for _ in range(2)]
    for thread in threads:
        thread.join(timeout=60)

    # Convergence: at least one creator succeeded; a loser may only fail
    # retryably (a live concurrent attempt, or its finalize rejected because
    # the winner's attempt superseded it).
    assert results, f"no creator succeeded; errors: {errors}"
    for error in errors:
        assert isinstance(
            error,
            (SandboxProvisioningInProgressError, StaleProvisioningAttemptError),
        )

    sandbox_rows = (
        db_session.query(Sandbox).filter(Sandbox.user_id == test_user.id).all()
    )
    session_rows = (
        db_session.query(BuildSession)
        .filter(BuildSession.user_id == test_user.id)
        .all()
    )
    assert len(sandbox_rows) == 1
    assert len(session_rows) == 1
    assert all(result == session_rows[0].id for result in results)
