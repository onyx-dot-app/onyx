"""Tests for the stuck-run sweeper.

Stuck runs are those whose row stayed in QUEUED past the queued
threshold (worker presumably never picked them up) or in RUNNING past
the running threshold (worker died mid-execution or the run blew past
its budget without crashing).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.scheduled_tasks.tasks import (
    cleanup_stuck_scheduled_runs,
)
from onyx.background.celery.tasks.scheduled_tasks.tasks import STUCK_QUEUED_OLDER_THAN
from onyx.background.celery.tasks.scheduled_tasks.tasks import STUCK_RUNNING_OLDER_THAN
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from onyx.db.scheduled_task import get_run
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture
def make_run(
    db_session: Session,
) -> Callable[..., ScheduledTaskRun]:
    """Insert a ScheduledTaskRun with explicit started_at."""

    def _factory(
        *,
        task_id: Any,
        status: ScheduledTaskRunStatus,
        started_at: datetime,
    ) -> ScheduledTaskRun:
        run = ScheduledTaskRun(
            task_id=task_id,
            status=status,
            trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
            started_at=started_at,
        )
        db_session.add(run)
        db_session.commit()
        db_session.refresh(run)
        return run

    return _factory


class TestStuckRunSweeper:
    def test_old_queued_and_running_marked_failed_fresh_left_alone(
        self,
        db_session: Session,
        make_task: Callable[..., ScheduledTask],
        make_run: Callable[..., ScheduledTaskRun],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        task = make_task(name="sweeper-test")
        now = datetime.now(tz=timezone.utc)

        # Far past either threshold.
        stuck_queued = make_run(
            task_id=task.id,
            status=ScheduledTaskRunStatus.QUEUED,
            started_at=now - STUCK_QUEUED_OLDER_THAN - timedelta(minutes=5),
        )
        stuck_running = make_run(
            task_id=task.id,
            status=ScheduledTaskRunStatus.RUNNING,
            started_at=now - STUCK_RUNNING_OLDER_THAN - timedelta(minutes=5),
        )
        # Fresh — should NOT be marked.
        fresh = make_run(
            task_id=task.id,
            status=ScheduledTaskRunStatus.QUEUED,
            started_at=now - timedelta(minutes=5),
        )

        # We can't assert the global count (other tests + leftover rows
        # may also be stuck) — just verify that THIS test's rows
        # transitioned correctly and `marked` includes them.
        marked = cleanup_stuck_scheduled_runs.run(tenant_id=TEST_TENANT_ID)
        assert marked >= 2

        db_session.expire_all()
        sq = get_run(db_session=db_session, run_id=stuck_queued.id)
        sr = get_run(db_session=db_session, run_id=stuck_running.id)
        fr = get_run(db_session=db_session, run_id=fresh.id)

        assert sq.status == ScheduledTaskRunStatus.FAILED
        assert sq.error_class == "stuck"
        assert sq.error_detail is not None and "queued" in sq.error_detail

        assert sr.status == ScheduledTaskRunStatus.FAILED
        assert sr.error_class == "stuck"
        assert sr.error_detail is not None and "running" in sr.error_detail

        assert fr.status == ScheduledTaskRunStatus.QUEUED
