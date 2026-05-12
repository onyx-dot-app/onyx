"""Tests for the scheduled-task dispatcher.

Covers the FOR UPDATE SKIP LOCKED claim path, the SKIP_IF_RUNNING
behavior when a prior run is still in flight, and that paused /
soft-deleted tasks are not claimed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.scheduled_tasks.tasks import (
    dispatch_due_scheduled_tasks,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from onyx.db.scheduled_task import insert_run
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


# Run signature mirrors the @shared_task wrapper. We call the underlying
# function via `.run` (Celery's idiom for invoking the wrapped callable
# in-process) and pass tenant_id as a kwarg, matching the per-tenant
# scheduling pattern used by other beat tasks.
def _call_dispatcher() -> int:
    return dispatch_due_scheduled_tasks.run(tenant_id=TEST_TENANT_ID)  # type: ignore[no-any-return]


def _all_runs_for_task(db_session: Session, task_id: Any) -> list[ScheduledTaskRun]:
    return list(
        db_session.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task_id)
        ).scalars()
    )


@pytest.fixture(autouse=True)
def _stub_enqueue() -> Any:
    """Prevent the dispatcher from actually pushing to Celery in tests.

    We assert the run rows directly; the executor enqueue is verified
    separately through send_task's call args.
    """
    with patch(
        "onyx.background.celery.tasks.scheduled_tasks.tasks."
        "dispatch_due_scheduled_tasks.app"
    ) as mock_app:
        mock_app.send_task.return_value = None
        yield mock_app


class TestDispatcherClaims:
    """Direct functional tests of `dispatch_due_scheduled_tasks`."""

    def test_due_tasks_get_queued_run_rows(
        self,
        db_session: Session,
        make_task: Callable[..., ScheduledTask],
        tenant_context: None,  # noqa: ARG002
        _stub_enqueue: Any,  # noqa: ARG002
    ) -> None:
        """Two due tasks → two QUEUED rows, next_run_at advanced.

        The Postgres test DB is shared across test runs so the dispatcher
        may legitimately claim leftover rows from other tests too. We
        verify only that the tasks owned by THIS test were claimed.
        """
        now = datetime.now(tz=timezone.utc)
        past = now - timedelta(minutes=2)
        task_a = make_task(name="a", cron_expression="*/5 * * * *", next_run_at=past)
        task_b = make_task(name="b", cron_expression="*/5 * * * *", next_run_at=past)

        result = _call_dispatcher()
        assert result >= 2  # may include leftover rows from other tests

        db_session.expire_all()
        runs_a = _all_runs_for_task(db_session, task_a.id)
        runs_b = _all_runs_for_task(db_session, task_b.id)
        assert len(runs_a) == 1
        assert len(runs_b) == 1
        assert runs_a[0].status == ScheduledTaskRunStatus.QUEUED
        assert runs_b[0].status == ScheduledTaskRunStatus.QUEUED
        assert runs_a[0].trigger_source == ScheduledTaskTriggerSource.SCHEDULED
        # next_run_at advanced to a future moment.
        db_session.refresh(task_a)
        db_session.refresh(task_b)
        assert task_a.next_run_at is not None and task_a.next_run_at > now
        assert task_b.next_run_at is not None and task_b.next_run_at > now

    def test_paused_and_deleted_tasks_not_claimed(
        self,
        db_session: Session,
        make_task: Callable[..., ScheduledTask],
        tenant_context: None,  # noqa: ARG002
        _stub_enqueue: Any,  # noqa: ARG002
    ) -> None:
        """Paused or soft-deleted rows must be excluded by the dispatcher."""
        past = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
        # Paused (next_run_at is set, but status is PAUSED)
        paused = make_task(
            status=ScheduledTaskStatus.PAUSED, next_run_at=past, name="paused"
        )
        deleted = make_task(deleted=True, next_run_at=past, name="deleted")
        active = make_task(name="active", next_run_at=past)

        # `>= 1` because other tests' tasks may also be due — we only
        # care that `active` was claimed and `paused`/`deleted` were not.
        result = _call_dispatcher()
        assert result >= 1

        db_session.expire_all()
        assert _all_runs_for_task(db_session, paused.id) == []
        assert _all_runs_for_task(db_session, deleted.id) == []
        active_runs = _all_runs_for_task(db_session, active.id)
        assert len(active_runs) == 1

    def test_prior_in_flight_writes_skipped_row(
        self,
        db_session: Session,
        make_task: Callable[..., ScheduledTask],
        tenant_context: None,  # noqa: ARG002
        _stub_enqueue: Any,  # noqa: ARG002
    ) -> None:
        """A QUEUED prior run blocks new dispatch; next_run_at still advances."""
        past = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
        task = make_task(name="rolling", next_run_at=past)

        # Simulate a prior run still in flight (RUNNING). Use the DB op
        # directly so we don't rely on the dispatcher.
        insert_run(
            db_session=db_session,
            task_id=task.id,
            trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
            status=ScheduledTaskRunStatus.RUNNING,
        )
        db_session.commit()
        db_session.refresh(task)
        prev_next = task.next_run_at

        result = _call_dispatcher()
        # The dispatcher counted the skipped row (plus any leftover
        # rows from other tests).
        assert result >= 1

        db_session.expire_all()
        runs = _all_runs_for_task(db_session, task.id)
        statuses = [r.status for r in runs]
        # Original RUNNING + new SKIPPED.
        assert ScheduledTaskRunStatus.RUNNING in statuses
        assert ScheduledTaskRunStatus.SKIPPED in statuses
        skipped_row = next(
            r for r in runs if r.status == ScheduledTaskRunStatus.SKIPPED
        )
        assert skipped_row.skip_reason == "prior_in_flight"
        # next_run_at advanced beyond `past`.
        db_session.refresh(task)
        assert task.next_run_at is not None
        assert prev_next is not None
        assert task.next_run_at > prev_next


class TestDispatcherConcurrency:
    """Verify FOR UPDATE SKIP LOCKED prevents double-claim."""

    def test_parallel_ticks_claim_each_row_once(
        self,
        db_session: Session,
        make_task: Callable[..., ScheduledTask],
        tenant_context: None,  # noqa: ARG002
        _stub_enqueue: Any,  # noqa: ARG002
    ) -> None:
        """Two threads call the dispatcher; only one run row is inserted."""
        SqlEngine.init_engine(pool_size=10, max_overflow=5)
        past = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
        task = make_task(name="contended", next_run_at=past)
        task_id = task.id

        results: list[int] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)

        def worker() -> None:
            # Each thread needs its own DB session + the tenant context.
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
            try:
                barrier.wait(timeout=5)
                with get_session_with_current_tenant():
                    pass  # pool warm-up
                results.append(_call_dispatcher())
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert not errors, f"Worker threads raised: {errors}"

        db_session.expire_all()
        runs = _all_runs_for_task(db_session, task_id)
        # The contention property we care about: exactly one QUEUED row
        # was inserted for this specific task, regardless of how the
        # parallel ticks interleaved.
        queued = [r for r in runs if r.status == ScheduledTaskRunStatus.QUEUED]
        assert len(queued) == 1
