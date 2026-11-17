import threading
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.cleanup.tasks import (
    export_query_history_cleanup_task,
)
from ee.onyx.background.task_name_builders import QUERY_HISTORY_TASK_NAME_PREFIX
from ee.onyx.db.query_history import get_all_query_history_export_tasks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import TaskStatus
from onyx.db.models import TaskQueueState
from onyx.db.tasks import (
    claim_task_with_id,
    get_started_task_for_update,
    get_task_with_id,
    mark_task_as_finished_with_id,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


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


def _run_export(task_id: str) -> None:
    from ee.onyx.background.celery.tasks.query_history.tasks import (
        export_query_history_task,
    )

    now = datetime.now(timezone.utc)
    export_query_history_task.apply(
        kwargs={"start": now, "end": now, "start_time": now, "tenant_id": "public"},
        task_id=task_id,
        throw=True,
    )


def _fail_export(task_id: str) -> None:
    with get_session_with_current_tenant() as other_session:
        mark_task_as_finished_with_id(other_session, task_id, success=False)


def test_cleanup_skips_a_row_a_worker_holds(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    held, other = export_rows[1], export_rows[0]
    with get_session_with_current_tenant() as worker_session:
        assert get_started_task_for_update(worker_session, held.task_id) is not None
        cleanup = threading.Thread(
            target=export_query_history_cleanup_task.run,
            kwargs={"tenant_id": "public"},
            daemon=True,
        )
        cleanup.start()
        cleanup.join(timeout=30)
        finished = not cleanup.is_alive()
        worker_session.rollback()
    cleanup.join(timeout=30)

    assert finished, "cleanup waited for a row lock that a worker holds"
    db_session.refresh(held)
    db_session.refresh(other)
    assert held.status == TaskStatus.STARTED
    assert other.status == TaskStatus.FAILURE


def test_worker_does_not_upload_an_export_failed_during_read(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    row = export_rows[0]
    with (
        patch(
            "ee.onyx.server.query_history.api.fetch_and_process_chat_session_history",
            side_effect=lambda **_: iter(_fail_export(row.task_id) or []),
        ),
        patch(
            "ee.onyx.background.celery.tasks.query_history.tasks.get_default_file_store"
        ) as file_store,
    ):
        _run_export(row.task_id)
    file_store.return_value.save_file.assert_not_called()
    db_session.refresh(row)
    assert row.status == TaskStatus.FAILURE


def test_worker_removes_an_upload_for_an_export_failed_during_upload(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    row = export_rows[0]
    with (
        patch(
            "ee.onyx.server.query_history.api.fetch_and_process_chat_session_history",
            return_value=iter([]),
        ),
        patch(
            "ee.onyx.background.celery.tasks.query_history.tasks.get_default_file_store"
        ) as file_store,
    ):
        file_store.return_value.save_file.side_effect = lambda **_: _fail_export(
            row.task_id
        )
        _run_export(row.task_id)
    file_store.return_value.save_file.assert_called_once()
    file_store.return_value.delete_file.assert_called_once()
    db_session.refresh(row)
    assert row.status == TaskStatus.FAILURE


def _started_exports(db_session: Session) -> set[str]:
    return {task.task_id for task in get_all_query_history_export_tasks(db_session)}


def test_failed_send_fails_the_new_export(db_session: Session) -> None:
    from ee.onyx.server.query_history.api import start_query_history_export

    before = _started_exports(db_session)
    with (
        patch("ee.onyx.server.query_history.api.ensure_query_history_is_enabled"),
        patch(
            "ee.onyx.server.query_history.api.client_app.send_task",
            side_effect=ConnectionError("broker down"),
        ),
        pytest.raises(OnyxError) as error,
    ):
        start_query_history_export(
            MagicMock(), db_session=db_session, start=None, end=None
        )
    assert error.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE
    new_ids = _started_exports(db_session) - before
    assert len(new_ids) == 1
    task = get_task_with_id(db_session, new_ids.pop())
    assert task is not None and task.status == TaskStatus.FAILURE
    db_session.delete(task)
    db_session.commit()
