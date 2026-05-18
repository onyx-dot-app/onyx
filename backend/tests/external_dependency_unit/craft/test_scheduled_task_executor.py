"""Cluster U — Scheduled tasks (executor half, ext-dep).

Drives the real ``run_scheduled_task_logic`` end-to-end against Postgres
with a stub ``SandboxManager``. The executor needs a ``SessionManager``,
which in turn instantiates ``SandboxManager`` via ``get_sandbox_manager``;
the fixture below redirects that import so the entire drive uses the
stub.

We also bypass ``SessionManager.create_session__no_commit`` because it
goes through provisioning, skill hydration, and workspace setup —
unnecessary surface for the executor's state-machine tests and not what
we're verifying here.
"""

from __future__ import annotations

import datetime
import threading
from typing import Any
from unittest.mock import patch
from unittest.mock import PropertyMock
from uuid import UUID
from uuid import uuid4

import pytest
from acp.schema import AgentMessageChunk
from acp.schema import PermissionOption
from acp.schema import PromptResponse
from acp.schema import RequestPermissionRequest
from acp.schema import ToolCallUpdate
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.scheduled_tasks.tasks import (
    cleanup_stuck_scheduled_runs,
)
from onyx.background.celery.tasks.scheduled_tasks.tasks import (
    dispatch_due_scheduled_tasks,
)
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.enums import SessionOrigin
from onyx.db.models import BuildSession
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from onyx.db.models import User
from onyx.server.features.build.scheduled_tasks.executor import run_scheduled_task_logic
from onyx.server.features.build.session import manager as session_manager_module
from onyx.server.features.build.session.manager import SessionManager
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import make_sandbox
from tests.external_dependency_unit.craft._test_helpers import make_user
from tests.external_dependency_unit.craft.stubs import StubSandboxManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stubbed_executor(
    stub_sandbox_manager: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> StubSandboxManager:
    """Wire ``SessionManager`` to use the stub manager + a lightweight session
    create that does no provisioning.

    Two patches:

    1. ``onyx.server.features.build.session.manager.get_sandbox_manager`` —
       SessionManager's ``__init__`` reads it at construction time.
    2. ``SessionManager.create_session__no_commit`` — bypass the full
       sandbox-provisioning path so the test focuses on executor state
       machine + persistence.
    """
    monkeypatch.setattr(
        session_manager_module, "get_sandbox_manager", lambda: stub_sandbox_manager
    )

    def _light_create_session(
        self: SessionManager,
        user_id: UUID,
        name: str | None = None,
        user_work_area: str | None = None,  # noqa: ARG001
        user_level: str | None = None,  # noqa: ARG001
        llm_provider_type: str | None = None,  # noqa: ARG001
        llm_model_name: str | None = None,  # noqa: ARG001
        origin: SessionOrigin = SessionOrigin.INTERACTIVE,
    ) -> BuildSession:
        row = BuildSession(
            user_id=user_id,
            name=name,
            status=BuildSessionStatus.ACTIVE,
            origin=origin,
        )
        self._db_session.add(row)
        self._db_session.flush()
        return row

    monkeypatch.setattr(
        SessionManager, "create_session__no_commit", _light_create_session
    )
    return stub_sandbox_manager


@pytest.fixture(autouse=True)
def _tenant_context(tenant_context: None) -> None:  # noqa: ARG001
    """All executor calls open their own DB session via
    ``get_session_with_current_tenant``, which needs the tenant contextvar
    set. Re-export the conftest fixture as autouse for clarity.
    """
    return None


def _make_text_chunk(text: str) -> AgentMessageChunk:
    return AgentMessageChunk.model_validate(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": text},
        }
    )


def _make_prompt_response() -> PromptResponse:
    return PromptResponse(stop_reason="end_turn")


def _make_permission_request(session_id: UUID) -> RequestPermissionRequest:
    return RequestPermissionRequest(
        options=[
            PermissionOption(
                kind="allow_once",
                name="Allow",
                option_id="allow",
            )
        ],
        session_id=str(session_id),
        tool_call=ToolCallUpdate(tool_call_id="tc-1"),
    )


def _seed_task_and_queued_run(
    db_session: Session, user: User
) -> tuple[ScheduledTask, ScheduledTaskRun]:
    task = ScheduledTask(
        user_id=user.id,
        name="nightly-report",
        prompt="Summarise yesterday's events",
        cron_expression="0 9 * * *",
        timezone="UTC",
        editor_mode="advanced",
        status=ScheduledTaskStatus.ACTIVE,
        next_run_at=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=1),
    )
    db_session.add(task)
    db_session.flush()
    run = ScheduledTaskRun(
        task_id=task.id,
        status=ScheduledTaskRunStatus.QUEUED,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
        started_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    db_session.refresh(task)
    return task, run


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_marks_queued_then_running(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_executor: StubSandboxManager,
) -> None:
    """Executor transitions QUEUED -> RUNNING before driving the agent.

    We observe the transition by snapshotting the run status in the
    middle of ``send_message`` — when the stub yields its first event,
    the run has already been flipped to RUNNING by the executor's
    Phase 1 commit.
    """
    user = make_user(db_session)
    make_sandbox(db_session, user)
    task, run = _seed_task_and_queued_run(db_session, user)

    observed_statuses: list[ScheduledTaskRunStatus] = []

    original_send_message = stubbed_executor.send_message

    def _send_message_observing(
        sandbox_id: UUID, session_id: UUID, message: str
    ) -> Any:
        # Re-read the run from a fresh session to observe the post-commit
        # transition the executor has already made.
        from onyx.db.engine.sql_engine import get_session_with_current_tenant

        with get_session_with_current_tenant() as fresh_session:
            row = fresh_session.get(ScheduledTaskRun, run.id)
            assert row is not None
            observed_statuses.append(row.status)
        return original_send_message(sandbox_id, session_id, message)

    stubbed_executor.send_message_events = [_make_prompt_response()]
    # Replace the bound method on the instance.
    stubbed_executor.send_message = _send_message_observing  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

    run_scheduled_task_logic(run.id)

    assert observed_statuses == [ScheduledTaskRunStatus.RUNNING]

    db_session.expire_all()
    final = db_session.get(ScheduledTaskRun, run.id)
    assert final is not None
    assert final.status == ScheduledTaskRunStatus.SUCCEEDED
    assert final.task_id == task.id


def test_run_succeeds_on_clean_stream(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_executor: StubSandboxManager,
) -> None:
    """Clean stream finishes with status=SUCCEEDED and a populated summary."""
    user = make_user(db_session)
    make_sandbox(db_session, user)
    _, run = _seed_task_and_queued_run(db_session, user)

    stubbed_executor.send_message_events = [
        _make_text_chunk("Done — pushed 3 commits."),
        _make_prompt_response(),
    ]

    run_scheduled_task_logic(run.id)

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    assert refreshed.status == ScheduledTaskRunStatus.SUCCEEDED
    assert refreshed.summary is not None
    assert "Done" in refreshed.summary
    assert refreshed.session_id is not None
    assert refreshed.finished_at is not None


def test_run_skipped_when_sandbox_unavailable(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_executor: StubSandboxManager,  # noqa: ARG001
) -> None:
    """Sleeping sandbox -> SKIPPED with skip_reason='sandbox_unavailable'."""
    user = make_user(db_session)
    make_sandbox(db_session, user, status=SandboxStatus.SLEEPING)
    _, run = _seed_task_and_queued_run(db_session, user)

    run_scheduled_task_logic(run.id)

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    assert refreshed.status == ScheduledTaskRunStatus.SKIPPED
    assert refreshed.skip_reason == "sandbox_unavailable"


def test_run_failed_on_budget_timeout(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_executor: StubSandboxManager,
) -> None:
    """Budget exceeded -> FAILED with error_class='timeout'.

    Forcing ``budget_seconds=0`` means the deadline check fires on the
    first non-permission event, which is exactly the path the production
    timeout takes when the agent overruns its 30-min budget.
    """
    user = make_user(db_session)
    make_sandbox(db_session, user)
    _, run = _seed_task_and_queued_run(db_session, user)

    stubbed_executor.send_message_events = [
        _make_text_chunk("starting..."),
        _make_text_chunk("still working..."),
        _make_prompt_response(),
    ]

    run_scheduled_task_logic(run.id, budget_seconds=0)

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    assert refreshed.status == ScheduledTaskRunStatus.FAILED
    assert refreshed.error_class == "timeout"


def test_run_failed_on_drive_loop_exception(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_executor: StubSandboxManager,
) -> None:
    """An exception raised inside ``send_message`` -> FAILED."""
    user = make_user(db_session)
    make_sandbox(db_session, user)
    _, run = _seed_task_and_queued_run(db_session, user)

    def _boom(
        sandbox_id: UUID,  # noqa: ARG001
        session_id: UUID,  # noqa: ARG001
        message: str,  # noqa: ARG001
    ) -> Any:
        raise RuntimeError("agent crashed mid-turn")
        yield  # pragma: no cover - generator marker

    stubbed_executor.send_message = _boom  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

    run_scheduled_task_logic(run.id)

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    assert refreshed.status == ScheduledTaskRunStatus.FAILED
    assert refreshed.error_class == "RuntimeError"
    assert refreshed.error_detail is not None
    assert "agent crashed" in refreshed.error_detail


def test_awaiting_approval_pauses_run(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_executor: StubSandboxManager,
) -> None:
    """A ``RequestPermissionRequest`` event flips status to AWAITING_APPROVAL."""
    user = make_user(db_session)
    make_sandbox(db_session, user)
    _, run = _seed_task_and_queued_run(db_session, user)

    placeholder_session_id = uuid4()
    stubbed_executor.send_message_events = [
        _make_text_chunk("Need approval to push..."),
        _make_permission_request(placeholder_session_id),
    ]

    run_scheduled_task_logic(run.id)

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    assert refreshed.status == ScheduledTaskRunStatus.AWAITING_APPROVAL
    # Awaiting-approval should NOT set finished_at — it's non-terminal.
    assert refreshed.finished_at is None


def test_dispatch_uses_skip_locked_to_avoid_dupes(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent dispatchers each claim a disjoint subset of due tasks.

    Concurrency contract: ``claim_due_scheduled_tasks`` uses
    ``SELECT ... FOR UPDATE SKIP LOCKED``, so simultaneous beat ticks
    must split the 3 due rows between them — every claimed task
    produces exactly one run row (QUEUED), and there is never a
    duplicate ``(task_id, status=QUEUED)`` insertion.
    """
    _ = monkeypatch  # autouse'd elsewhere; kept for symmetry with sibling tests
    user = make_user(db_session)
    now = datetime.datetime.now(datetime.timezone.utc)
    task_ids: list[UUID] = []
    for i in range(3):
        task = ScheduledTask(
            user_id=user.id,
            name=f"due-{i}",
            prompt=f"prompt-{i}",
            cron_expression="* * * * *",
            timezone="UTC",
            editor_mode="advanced",
            status=ScheduledTaskStatus.ACTIVE,
            next_run_at=now - datetime.timedelta(seconds=10),
        )
        db_session.add(task)
        db_session.flush()
        task_ids.append(task.id)
    db_session.commit()

    # Each thread runs the dispatch task body inside its own tenant context
    # + DB session. The post-commit ``send_task`` enqueue is mocked so we
    # don't need a real broker.
    results: dict[int, int] = {}
    barrier = threading.Barrier(2)

    # ``self.app`` is a property on the Celery-generated Task subclass;
    # we patch the property to return a fake whose ``send_task`` is a
    # no-op so the dispatcher never touches a broker.
    task_instance = dispatch_due_scheduled_tasks.run.__self__  # type: ignore[attr-defined]

    class _FakeApp:
        def send_task(
            self,
            *args: Any,  # noqa: ARG002
            **kwargs: Any,  # noqa: ARG002
        ) -> None:
            return None

    fake_app = _FakeApp()

    def _dispatch_in_thread(idx: int) -> None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
        try:
            barrier.wait(timeout=5)
            results[idx] = dispatch_due_scheduled_tasks.run(tenant_id=TEST_TENANT_ID)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    with patch.object(
        type(task_instance),
        "app",
        new_callable=PropertyMock,
        return_value=fake_app,
    ):
        t1 = threading.Thread(target=_dispatch_in_thread, args=(0,))
        t2 = threading.Thread(target=_dispatch_in_thread, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        assert not t1.is_alive() and not t2.is_alive()

    # Each due task produced exactly one run row.
    db_session.expire_all()
    runs = (
        db_session.query(ScheduledTaskRun)
        .filter(ScheduledTaskRun.task_id.in_(task_ids))
        .all()
    )
    assert len(runs) == 3
    seen_task_ids = {r.task_id for r in runs}
    assert seen_task_ids == set(task_ids)
    # No task got dispatched twice.
    by_task: dict[UUID, list[ScheduledTaskRun]] = {}
    for r in runs:
        by_task.setdefault(r.task_id, []).append(r)
    assert all(len(v) == 1 for v in by_task.values())

    # Both dispatcher threads must have completed and returned a count.
    assert len(results) == 2, (
        f"Expected results from both dispatcher threads; got {results}"
    )
    assert all(isinstance(v, int) and v >= 0 for v in results.values()), (
        f"Dispatcher thread returned invalid result: {results}"
    )
    # The two dispatchers together claimed exactly 3 — no double-fire.
    assert sum(results.values()) == 3


def test_soft_deleted_task_does_not_abort_queued_run(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stubbed_executor: StubSandboxManager,
) -> None:
    """Task soft-deleted *after* dispatch but *before* executor runs → run completes.

    Pins the V1 contract (see ``craft-behaviors.md`` §1.8 and the executor's
    own comment around the ``task = run.task`` lookup): once a run has been
    queued, a subsequent soft-delete of the owning task must NOT abort the
    in-flight execution — it should run to completion using the ORM
    relationship rather than a deleted-filter lookup.
    """
    user = make_user(db_session)
    make_sandbox(db_session, user)
    task, run = _seed_task_and_queued_run(db_session, user)

    # Soft-delete the task BEFORE the executor picks up the run.
    task.deleted = True
    db_session.commit()

    stubbed_executor.send_message_events = [
        _make_text_chunk("ran anyway"),
        _make_prompt_response(),
    ]

    run_scheduled_task_logic(run.id)

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    # Contract: in-flight run survives the soft-delete and completes.
    assert refreshed.status == ScheduledTaskRunStatus.SUCCEEDED
    assert refreshed.finished_at is not None


def test_cleanup_stuck_runs_marks_queued_over_threshold_failed(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A QUEUED run older than 15 min → ``cleanup_stuck_scheduled_runs`` marks it FAILED."""
    user = make_user(db_session)
    task = ScheduledTask(
        user_id=user.id,
        name="stale",
        prompt="...",
        cron_expression="0 9 * * *",
        timezone="UTC",
        editor_mode="advanced",
        status=ScheduledTaskStatus.ACTIVE,
        next_run_at=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=1),
    )
    db_session.add(task)
    db_session.flush()
    stale_started = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        minutes=20
    )
    run = ScheduledTaskRun(
        task_id=task.id,
        status=ScheduledTaskRunStatus.QUEUED,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
        started_at=stale_started,
    )
    db_session.add(run)
    db_session.commit()

    marked = cleanup_stuck_scheduled_runs.run(tenant_id=TEST_TENANT_ID)
    assert marked >= 1

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    assert refreshed.status == ScheduledTaskRunStatus.FAILED
    assert refreshed.error_class == "stuck"


def test_cleanup_stuck_runs_marks_running_over_threshold_failed(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A RUNNING run older than the running threshold → ``cleanup_stuck_scheduled_runs`` marks it FAILED.

    Production threshold is ``DEFAULT_EXECUTOR_BUDGET_SECONDS + 15 min`` (i.e.
    45 min). Backdating ``started_at`` by 50 min puts the run past that.
    """
    user = make_user(db_session)
    task = ScheduledTask(
        user_id=user.id,
        name="long-running",
        prompt="...",
        cron_expression="0 9 * * *",
        timezone="UTC",
        editor_mode="advanced",
        status=ScheduledTaskStatus.ACTIVE,
        next_run_at=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=1),
    )
    db_session.add(task)
    db_session.flush()
    stale_started = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        minutes=50
    )
    run = ScheduledTaskRun(
        task_id=task.id,
        status=ScheduledTaskRunStatus.RUNNING,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
        started_at=stale_started,
    )
    db_session.add(run)
    db_session.commit()

    marked = cleanup_stuck_scheduled_runs.run(tenant_id=TEST_TENANT_ID)
    assert marked >= 1

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    assert refreshed.status == ScheduledTaskRunStatus.FAILED
    assert refreshed.error_class == "stuck"
