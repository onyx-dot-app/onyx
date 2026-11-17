from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.server.reporting.usage_export_api import (
    GenerateUsageReportParams,
    generate_report,
)
from ee.onyx.server.reporting.usage_export_models import USAGE_REPORT_MEDIA_TYPE
from onyx.configs.constants import FileOrigin
from onyx.db.models import TaskQueueState
from onyx.db.tasks import get_task_with_id


@pytest.fixture
def report_id(db_session: Session) -> Generator[str, None, None]:
    report_id = str(uuid4())
    yield report_id
    db_session.rollback()
    db_session.query(TaskQueueState).filter_by(task_id=report_id).delete()
    db_session.commit()


def test_api_persists_report_before_dispatch(
    db_session: Session, report_id: str
) -> None:
    with patch(
        "ee.onyx.server.reporting.usage_export_api.client_app.send_task"
    ) as send:
        generate_report(
            GenerateUsageReportParams(report_id=report_id),
            user=MagicMock(),
            db_session=db_session,
        )
    row = get_task_with_id(db_session, report_id)
    assert row is not None
    assert row.status == "PENDING"
    assert send.call_args.kwargs["task_id"] == report_id
    assert send.call_args.kwargs["expires"] == 3600


@pytest.mark.parametrize("status", ["PENDING", "STARTED"])
def test_lost_report_is_visible_as_failure(
    db_session: Session, report_id: str, status: str
) -> None:
    from ee.onyx.background.celery.tasks.cleanup.tasks import (
        export_query_history_cleanup_task,
    )
    from ee.onyx.background.celery.tasks.usage_reporting.tasks import (
        generate_usage_report_task,
    )
    from ee.onyx.server.reporting.usage_export_api import fetch_usage_report_jobs
    from onyx.configs.constants import OnyxCeleryTask
    from onyx.db.enums import TaskStatus
    from onyx.db.tasks import register_task

    row = register_task(
        f"{OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK}_{report_id}",
        db_session,
        report_id,
    )
    old = datetime.now(timezone.utc) - timedelta(days=1)
    row.register_time = old
    row.start_time = old
    row.status = TaskStatus(status)
    db_session.commit()
    export_query_history_cleanup_task.run(tenant_id="public")
    db_session.expire_all()
    jobs = fetch_usage_report_jobs(db_session=db_session)
    assert (
        next(job for job in jobs if str(job.report_id) == report_id).status
        == TaskStatus.FAILURE
    )
    with patch(
        "ee.onyx.server.reporting.usage_export_generation.create_new_usage_report"
    ) as generate:
        generate_usage_report_task.apply(
            task_id=report_id,
            kwargs={"tenant_id": "public", "report_id": report_id, "track_job": True},
            throw=True,
        )
        generate.assert_not_called()


def test_worker_exception_is_visible(db_session: Session, report_id: str) -> None:
    from ee.onyx.background.celery.tasks.usage_reporting.tasks import (
        generate_usage_report_task,
    )
    from onyx.configs.constants import OnyxCeleryTask
    from onyx.db.tasks import register_task

    register_task(
        f"{OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK}_{report_id}",
        db_session,
        report_id,
    )
    with patch(
        "ee.onyx.server.reporting.usage_export_generation.create_new_usage_report",
        side_effect=RuntimeError("generation failed"),
    ):
        with pytest.raises(RuntimeError, match="generation failed"):
            generate_usage_report_task.apply(
                task_id=report_id,
                kwargs={
                    "tenant_id": "public",
                    "report_id": report_id,
                    "track_job": True,
                },
                throw=True,
            )
    db_session.expire_all()
    row = get_task_with_id(db_session, report_id)
    assert row is not None and row.status == "FAILURE"


@pytest.mark.parametrize("tracked", [False, True])
def test_success_commits_report_and_removes_job(
    db_session: Session, report_id: str, tracked: bool
) -> None:
    from ee.onyx.background.celery.tasks.usage_reporting.tasks import (
        generate_usage_report_task,
    )
    from onyx.configs.constants import OnyxCeleryTask
    from onyx.db.models import UsageReport
    from onyx.db.tasks import register_task
    from onyx.file_store.file_store import get_default_file_store

    if tracked:
        register_task(
            f"{OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK}_{report_id}",
            db_session,
            report_id,
        )
    report_name: str | None = None
    try:
        generate_usage_report_task.apply(
            task_id=report_id,
            kwargs={
                "tenant_id": "public",
                "report_id": report_id,
                "track_job": tracked,
            },
            throw=True,
        )
        db_session.expire_all()
        assert get_task_with_id(db_session, report_id) is None
        report = (
            db_session.query(UsageReport)
            .filter(UsageReport.report_name.contains(report_id))
            .one()
        )
        report_name = report.report_name
        assert get_default_file_store().has_file(
            report_name, FileOrigin.GENERATED_REPORT, USAGE_REPORT_MEDIA_TYPE
        )
    finally:
        db_session.rollback()
        db_session.query(UsageReport).filter(
            UsageReport.report_name.contains(report_id)
        ).delete()
        db_session.commit()
        if report_name:
            get_default_file_store().delete_file(report_name, error_on_missing=False)


def test_reaped_generation_cannot_publish(db_session: Session, report_id: str) -> None:
    from ee.onyx.server.reporting.usage_export_generation import create_new_usage_report
    from onyx.configs.constants import OnyxCeleryTask
    from onyx.db.enums import TaskStatus
    from onyx.db.tasks import register_task
    from onyx.file_store.file_store import get_default_file_store

    register_task(
        f"{OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK}_{report_id}",
        db_session,
        report_id,
        status=TaskStatus.FAILURE,
    )
    with pytest.raises(RuntimeError, match="already ended"):
        create_new_usage_report(
            db_session,
            user_id=None,
            period=None,
            report_id=report_id,
            task_id=report_id,
        )
    db_session.rollback()
    report_name = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}_{report_id}_usage_report.zip"
    assert not get_default_file_store().has_file(
        report_name, FileOrigin.GENERATED_REPORT, USAGE_REPORT_MEDIA_TYPE
    )


def test_concurrent_report_ids_register_only_one_job(
    db_session: Session, report_id: str
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import UUID

    from ee.onyx.db.usage_export import register_usage_report_job
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import OnyxError

    barrier = Barrier(2)

    def register() -> str:
        with get_session_with_current_tenant() as session:
            barrier.wait(timeout=10)
            try:
                register_usage_report_job(session, UUID(report_id))
                return "registered"
            except OnyxError as error:
                assert error.error_code == OnyxErrorCode.DUPLICATE_RESOURCE
                return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: register(), range(2)))
    assert sorted(results) == ["duplicate", "registered"]
    assert db_session.query(TaskQueueState).filter_by(task_id=report_id).count() == 1


def test_failed_send_fails_the_new_report(db_session: Session, report_id: str) -> None:
    from onyx.db.enums import TaskStatus
    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import OnyxError

    with (
        patch(
            "ee.onyx.server.reporting.usage_export_api.client_app.send_task",
            side_effect=ConnectionError("broker down"),
        ),
        pytest.raises(OnyxError) as error,
    ):
        generate_report(
            GenerateUsageReportParams(report_id=report_id),
            user=MagicMock(),
            db_session=db_session,
        )
    assert error.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE
    db_session.expire_all()
    row = get_task_with_id(db_session, report_id)
    assert row is not None and row.status == TaskStatus.FAILURE


def test_job_failed_during_upload_removes_the_zip(
    db_session: Session, report_id: str
) -> None:
    from sqlalchemy import text

    from ee.onyx.server.reporting.usage_export_generation import create_new_usage_report
    from onyx.configs.constants import OnyxCeleryTask
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.db.enums import TaskStatus
    from onyx.db.tasks import fail_task_with_id, register_task
    from onyx.file_store.file_store import get_default_file_store

    register_task(
        f"{OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK}_{report_id}",
        db_session,
        report_id,
        status=TaskStatus.STARTED,
    )
    real_store = get_default_file_store()
    uploaded: list[str] = []

    def save_file(**kwargs: object) -> str:
        if kwargs.get("file_type") == USAGE_REPORT_MEDIA_TYPE:
            # Cleanup fails the job while the ZIP uploads. It must not wait.
            with get_session_with_current_tenant() as cleanup_session:
                cleanup_session.execute(text("SET LOCAL lock_timeout = '5s'"))
                fail_task_with_id(cleanup_session, report_id, TaskStatus.STARTED)
            uploaded.append(str(kwargs["file_id"]))
        return real_store.save_file(**kwargs)  # ty: ignore[invalid-argument-type]

    store = MagicMock(wraps=real_store)
    store.save_file.side_effect = save_file
    with (
        patch(
            "ee.onyx.server.reporting.usage_export_generation.get_default_file_store",
            return_value=store,
        ),
        pytest.raises(RuntimeError, match="already ended"),
    ):
        create_new_usage_report(
            db_session,
            user_id=None,
            period=None,
            report_id=report_id,
            task_id=report_id,
        )
    assert len(uploaded) == 1
    assert not real_store.has_file(
        uploaded[0], FileOrigin.GENERATED_REPORT, USAGE_REPORT_MEDIA_TYPE
    )
    db_session.rollback()
    db_session.expire_all()
    row = get_task_with_id(db_session, report_id)
    assert row is not None and row.status == TaskStatus.FAILURE
