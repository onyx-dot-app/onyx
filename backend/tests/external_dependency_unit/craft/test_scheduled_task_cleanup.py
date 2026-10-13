"""Committed test schedules must not survive fixture teardown."""

from contextlib import nullcontext
from typing import Literal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ScheduledTaskRunStatus,
    ScheduledTaskStatus,
    ScheduledTaskTriggerSource,
)
from onyx.db.models import ScheduledTask, ScheduledTaskRun, User
from tests.external_dependency_unit.craft.db_helpers import scheduled_task_cleanup


def _task(user: User) -> ScheduledTask:
    return ScheduledTask(
        user_id=user.id,
        name="cleanup-regression",
        prompt="test",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        status=ScheduledTaskStatus.PAUSED,
    )


@pytest.mark.parametrize("failure", [None, "assertion", "transaction"])
def test_cleanup_removes_only_created_schedules(
    db_session: Session,
    test_user: User,
    failure: Literal["assertion", "transaction"] | None,
) -> None:
    existing = _task(test_user)
    db_session.add(existing)
    db_session.commit()
    existing_id = existing.id
    task = _task(test_user)
    expected_error = AssertionError if failure == "assertion" else DBAPIError

    with pytest.raises(expected_error) if failure else nullcontext():
        with scheduled_task_cleanup(db_session):
            db_session.add(task)
            db_session.flush()
            run = ScheduledTaskRun(
                task_id=task.id,
                status=ScheduledTaskRunStatus.QUEUED,
                trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
            )
            db_session.add(run)
            db_session.commit()
            task_id, run_id = task.id, run.id
            if failure == "assertion":
                raise AssertionError("test failed after commit")
            if failure == "transaction":
                db_session.execute(text("SELECT 1 / 0"))

    with get_session_with_current_tenant() as verification:
        assert verification.get(ScheduledTask, task_id) is None
        assert verification.get(ScheduledTaskRun, run_id) is None
        assert verification.get(ScheduledTask, existing_id) is not None
