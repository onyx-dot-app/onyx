from datetime import datetime
from uuid import UUID

from celery import Task, shared_task

from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import TaskStatus
from onyx.db.tasks import claim_task_with_id, fail_task_with_id, get_task_with_id
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def generate_usage_report_task(
    self: Task,
    *,
    tenant_id: str,  # noqa: ARG001
    user_id: str | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
    report_id: str | None = None,
) -> None:
    """User-initiated usage report generation task"""
    from ee.onyx.server.reporting.usage_export_generation import create_new_usage_report

    task_id = self.request.id
    with get_session_with_current_tenant() as db_session:
        # A manual request saves a job row under its task id first. A scheduled
        # run, or a task sent before job rows existed, has none.
        tracked = (
            task_id is not None and get_task_with_id(db_session, task_id) is not None
        )
        if tracked and not claim_task_with_id(db_session, task_id):
            return
        try:
            period = None
            if period_from and period_to:
                period = (
                    datetime.fromisoformat(period_from),
                    datetime.fromisoformat(period_to),
                )
            create_new_usage_report(
                db_session=db_session,
                user_id=UUID(user_id) if user_id else None,
                period=period,
                report_id=report_id,
                task_id=task_id if tracked else None,
            )
        except Exception:
            if tracked:
                fail_task_with_id(db_session, task_id, TaskStatus.STARTED)
            raise
