from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.cleanup.tasks import (
    export_query_history_cleanup_task,
)
from ee.onyx.background.task_name_builders import QUERY_HISTORY_TASK_NAME_PREFIX
from onyx.db.enums import TaskStatus
from onyx.db.models import TaskQueueState
from onyx.db.tasks import claim_task_with_id


@pytest.fixture
def export_rows(db_session: Session) -> Generator[list[TaskQueueState], None, None]:
    rows: list[TaskQueueState] = []
    for status, age in (
        (TaskStatus.PENDING, 48),
        (TaskStatus.STARTED, 48),
        (TaskStatus.PENDING, 0),
        (TaskStatus.STARTED, 0),
    ):
        when = datetime.now(timezone.utc) - timedelta(hours=age)
        row = TaskQueueState(
            task_id=str(uuid4()),
            task_name=f"{QUERY_HISTORY_TASK_NAME_PREFIX}_{uuid4()}",
            status=status,
            register_time=when,
            start_time=when,
        )
        db_session.add(row)
        rows.append(row)
    db_session.commit()
    yield rows
    db_session.rollback()
    for row in rows:
        db_session.delete(row)
    db_session.commit()


def test_cleanup_fails_lost_exports(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    export_query_history_cleanup_task.run(tenant_id="public")
    for row in export_rows:
        db_session.refresh(row)

    assert [row.status for row in export_rows] == [
        TaskStatus.FAILURE,
        TaskStatus.FAILURE,
        TaskStatus.PENDING,
        TaskStatus.STARTED,
    ]
    # A second cleanup must keep the new failures visible for 24 hours.
    export_query_history_cleanup_task.run(tenant_id="public")
    for row in export_rows:
        db_session.refresh(row)


def test_cleanup_does_not_fail_a_worker_that_just_claimed_an_old_row(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    row = export_rows[0]
    assert claim_task_with_id(db_session, row.task_id)
    export_query_history_cleanup_task.run(tenant_id="public")
    db_session.refresh(row)
    assert row.status == TaskStatus.STARTED
    assert not claim_task_with_id(db_session, row.task_id)


def test_late_worker_drops_failed_export(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    from ee.onyx.background.celery.tasks.query_history.tasks import (
        export_query_history_task,
    )

    row = export_rows[0]
    export_query_history_cleanup_task.run(tenant_id="public")
    with patch(
        "ee.onyx.server.query_history.api.fetch_and_process_chat_session_history"
    ) as fetch:
        now = datetime.now(timezone.utc)
        export_query_history_task.apply(
            kwargs={"start": now, "end": now, "start_time": now, "tenant_id": "public"},
            task_id=row.task_id,
            throw=True,
        )
        fetch.assert_not_called()
    db_session.refresh(row)
    assert row.status == TaskStatus.FAILURE
