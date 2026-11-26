import io
import threading
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.cleanup.tasks import (
    export_query_history_cleanup_task,
)
from ee.onyx.background.task_name_builders import QUERY_HISTORY_TASK_NAME_PREFIX
from ee.onyx.db.query_history import get_all_query_history_export_tasks
from onyx.background.task_utils import construct_query_history_report_name
from onyx.configs.constants import FileOrigin, FileType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import TaskStatus
from onyx.db.models import TaskQueueState
from onyx.db.tasks import (
    claim_task_with_id,
    fail_task_with_id,
    get_started_task_for_update,
    get_task_with_id,
    register_task,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store


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

    expected = [
        TaskStatus.FAILURE,
        TaskStatus.FAILURE,
        TaskStatus.PENDING,
        TaskStatus.STARTED,
    ]
    assert [row.status for row in export_rows] == expected
    # A second cleanup must keep the new failures visible for 24 hours.
    export_query_history_cleanup_task.run(tenant_id="public")
    for row in export_rows:
        db_session.refresh(row)
    assert [row.status for row in export_rows] == expected


def test_cleanup_does_not_fail_a_worker_that_just_claimed_an_old_row(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    row = export_rows[0]
    assert claim_task_with_id(db_session, row.task_id)
    export_query_history_cleanup_task.run(tenant_id="public")
    db_session.refresh(row)
    assert row.status == TaskStatus.STARTED
    assert not claim_task_with_id(db_session, row.task_id)


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


def test_late_worker_drops_failed_export(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    row = export_rows[0]
    export_query_history_cleanup_task.run(tenant_id="public")
    with patch(
        "ee.onyx.server.query_history.api.fetch_and_process_chat_session_history"
    ) as fetch:
        _run_export(row.task_id)
        fetch.assert_not_called()
    db_session.refresh(row)
    assert row.status == TaskStatus.FAILURE


def _fail_export(task_id: str) -> None:
    with get_session_with_current_tenant() as other_session:
        fail_task_with_id(other_session, task_id, TaskStatus.STARTED)


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


def _open_transactions() -> int:
    with get_session_with_current_tenant() as session:
        return session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = "
                "current_database() AND state = 'idle in transaction' "
                "AND pid <> pg_backend_pid()"
            )
        )


def test_upload_runs_without_an_open_transaction(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    row = export_rows[0]
    db_session.commit()
    open_during_upload: list[int] = []
    with (
        patch(
            "ee.onyx.server.query_history.api.fetch_and_process_chat_session_history",
            return_value=iter([]),
        ),
        patch(
            "ee.onyx.background.celery.tasks.query_history.tasks.get_default_file_store"
        ) as file_store,
    ):
        file_store.return_value.save_file.side_effect = lambda **_: (
            open_during_upload.append(_open_transactions())
        )
        _run_export(row.task_id)
    assert open_during_upload == [0]


def _export_task_ids(db_session: Session) -> set[str]:
    return {task.task_id for task in get_all_query_history_export_tasks(db_session)}


def test_failed_send_fails_the_new_export(db_session: Session) -> None:
    from ee.onyx.server.query_history.api import start_query_history_export

    before = _export_task_ids(db_session)
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
    new_ids = _export_task_ids(db_session) - before
    assert len(new_ids) == 1
    task = get_task_with_id(db_session, new_ids.pop())
    assert task is not None and task.status == TaskStatus.FAILURE
    db_session.delete(task)
    db_session.commit()


def test_file_of_a_failed_export_is_not_published(db_session: Session) -> None:
    from ee.onyx.background.task_name_builders import query_history_task_name
    from ee.onyx.server.query_history.api import (
        download_query_history_csv,
        list_all_query_history_exports,
    )

    when = datetime.now(timezone.utc)
    row = register_task(
        task_name=query_history_task_name(start=when - timedelta(days=1), end=when),
        db_session=db_session,
        task_id=str(uuid4()),
        status=TaskStatus.FAILURE,
        # Failure moves start_time. The list must still show the request time.
        start_time=when + timedelta(hours=1),
    )
    report_name = construct_query_history_report_name(row.task_id)
    now = when.isoformat()
    file_store = get_default_file_store()
    # A late upload whose delete has not run yet.
    file_store.save_file(
        content=io.BytesIO(b"leaked"),
        display_name=report_name,
        file_origin=FileOrigin.QUERY_HISTORY_CSV,
        file_type=FileType.CSV,
        file_metadata={"start": now, "end": now, "start_time": now},
        file_id=report_name,
    )
    try:
        with patch("ee.onyx.server.query_history.api.ensure_query_history_is_enabled"):
            exports = list_all_query_history_exports(MagicMock(), db_session=db_session)
            with pytest.raises(OnyxError):
                download_query_history_csv(
                    row.task_id, MagicMock(), db_session=db_session
                )
        listed = [e for e in exports if e.task_id == row.task_id]
        assert [e.status for e in listed] == [TaskStatus.FAILURE]
        assert listed[0].start_time == row.register_time
    finally:
        file_store.delete_file(report_name, error_on_missing=False)
        db_session.rollback()
        db_session.delete(row)
        db_session.commit()


def test_cleanup_deletes_the_file_of_an_expired_failure(db_session: Session) -> None:
    from ee.onyx.background.task_name_builders import query_history_task_name
    from ee.onyx.server.query_history.api import list_all_query_history_exports

    when = datetime.now(timezone.utc) - timedelta(days=2)
    row = register_task(
        task_name=query_history_task_name(start=when, end=when),
        db_session=db_session,
        task_id=str(uuid4()),
        status=TaskStatus.FAILURE,
        start_time=when,
    )
    task_id = row.task_id
    report_name = construct_query_history_report_name(task_id)
    file_store = get_default_file_store()
    # The worker stopped after its upload, before it published the file.
    file_store.save_file(
        content=io.BytesIO(b"unpublished"),
        display_name=report_name,
        file_origin=FileOrigin.QUERY_HISTORY_CSV,
        file_type=FileType.CSV,
        file_metadata={
            "start": when.isoformat(),
            "end": when.isoformat(),
            "start_time": when.isoformat(),
        },
        file_id=report_name,
    )
    try:
        export_query_history_cleanup_task.run(tenant_id="public")
        db_session.expire_all()
        assert get_task_with_id(db_session, task_id) is None
        assert not file_store.has_file(
            file_id=report_name,
            file_origin=FileOrigin.QUERY_HISTORY_CSV,
            file_type=FileType.CSV,
        )
        with patch("ee.onyx.server.query_history.api.ensure_query_history_is_enabled"):
            exports = list_all_query_history_exports(MagicMock(), db_session=db_session)
        assert task_id not in {export.task_id for export in exports}
    finally:
        file_store.delete_file(report_name, error_on_missing=False)
        db_session.rollback()
        leftover = get_task_with_id(db_session, task_id)
        if leftover is not None:
            db_session.delete(leftover)
            db_session.commit()


def test_failed_file_delete_keeps_its_row_and_cleanup_continues(
    db_session: Session, export_rows: list[TaskQueueState]
) -> None:
    when = datetime.now(timezone.utc) - timedelta(days=2)
    expired = TaskQueueState(
        task_id=str(uuid4()),
        task_name=f"{QUERY_HISTORY_TASK_NAME_PREFIX}_{uuid4()}",
        status=TaskStatus.FAILURE,
        register_time=when,
        start_time=when,
    )
    db_session.add(expired)
    db_session.commit()
    try:
        with patch(
            "ee.onyx.background.celery.tasks.cleanup.tasks.get_default_file_store"
        ) as file_store:
            file_store.return_value.delete_file.side_effect = ConnectionError(
                "storage down"
            )
            export_query_history_cleanup_task.run(tenant_id="public")
        db_session.expire_all()
        # The row keeps hiding the file that cleanup could not delete.
        assert get_task_with_id(db_session, expired.task_id) is not None
        assert [row.status for row in export_rows[:2]] == [
            TaskStatus.FAILURE,
            TaskStatus.FAILURE,
        ]
    finally:
        db_session.rollback()
        db_session.delete(expired)
        db_session.commit()
