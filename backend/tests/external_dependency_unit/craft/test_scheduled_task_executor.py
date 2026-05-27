"""Scheduled tasks (executor half, ext-dep).

Drives the real ``run_scheduled_task_logic`` end-to-end against Postgres
and the real ``LocalSandboxManager``. Scope of this file:

* Dispatcher concurrency (``SELECT ... FOR UPDATE SKIP LOCKED``).
* Stuck-run cleanup sweeper.
* The executor's wake-failure contract — when
  ``SessionManager.ensure_sandbox_running`` raises, the run is marked
  ``FAILED`` with ``error_class=sandbox_wake_failed``.

State-machine coverage for ``ensure_sandbox_running`` itself
(SLEEPING / TERMINATED / FAILED → wake, PROVISIONING → wait, etc.) lives
in ``test_ensure_sandbox_running.py`` and is not duplicated here — the
executor merely delegates to that API.
"""

from __future__ import annotations

import datetime
import threading
from typing import Any
from unittest.mock import patch
from unittest.mock import PropertyMock
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.scheduled_tasks.tasks import (
    cleanup_stuck_scheduled_runs,
)
from onyx.background.celery.tasks.scheduled_tasks.tasks import (
    dispatch_due_scheduled_tasks,
)
from onyx.db.enums import SandboxStatus
from onyx.db.enums import ScheduledTaskErrorClass
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from onyx.db.models import User
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.scheduled_tasks.executor import run_scheduled_task_logic
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import make_sandbox
from tests.external_dependency_unit.craft._test_helpers import make_user

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _tenant_context(tenant_context: None) -> None:  # noqa: ARG001
    """All executor calls open their own DB session via
    ``get_session_with_current_tenant``, which needs the tenant contextvar
    set. Re-export the conftest fixture as autouse for clarity.
    """
    return None


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


@pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="Exercises run_scheduled_task_logic → SessionManager → real "
    "KubernetesSandboxManager init; requires SANDBOX_BACKEND=kubernetes "
    "(runs in the dedicated K8s CI job).",
)
def test_run_fails_when_wake_fails(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ensure_sandbox_running`` raising → run FAILED / ``sandbox_wake_failed``.

    Trigger a deterministic wake failure by seeding the sandbox as
    ``PROVISIONING`` and dropping the executor's wait window to 0s so
    ``_wait_for_provisioning_to_complete`` raises ``SandboxProvisioningError``
    on the first deadline check. That's the executor's Phase-1
    try/except path, which must translate any exception escaping
    ``ensure_sandbox_running`` into ``FAILED`` with
    ``error_class=sandbox_wake_failed``.

    "How we got there" (which specific state triggered the wake, which
    inner call raised) is intentionally out of scope — this test pins
    only the executor's contract.
    """
    monkeypatch.setattr(
        "onyx.server.features.build.scheduled_tasks.executor.PROVISIONING_WAIT_SECONDS",
        0,
    )

    user = make_user(db_session)
    make_sandbox(db_session, user, status=SandboxStatus.PROVISIONING)
    _, run = _seed_task_and_queued_run(db_session, user)

    run_scheduled_task_logic(run.id)

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    assert refreshed.status == ScheduledTaskRunStatus.FAILED
    assert refreshed.error_class == ScheduledTaskErrorClass.SANDBOX_WAKE_FAILED.value


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
