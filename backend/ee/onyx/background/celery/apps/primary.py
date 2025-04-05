from datetime import datetime

from celery import Task

from ee.onyx.background.celery.tasks.query_history import query_history_report
from ee.onyx.background.celery_utils import should_perform_chat_ttl_check
from ee.onyx.background.task_name_builders import name_chat_ttl_task
from ee.onyx.background.task_name_builders import name_query_history_report_task
from ee.onyx.server.reporting.usage_export_generation import create_new_usage_report
from onyx.background.celery.apps.primary import celery_app
from onyx.background.task_utils import build_celery_task_wrapper
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.db.chat import delete_chat_session
from onyx.db.chat import get_chat_sessions_older_than
from onyx.db.engine import get_session_with_current_tenant
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger

logger = setup_logger()

# mark as EE for all tasks in this file


@build_celery_task_wrapper(name_chat_ttl_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def perform_ttl_management_task(retention_limit_days: int, *, tenant_id: str) -> None:
    with get_session_with_current_tenant() as db_session:
        old_chat_sessions = get_chat_sessions_older_than(
            retention_limit_days, db_session
        )

    for user_id, session_id in old_chat_sessions:
        # one session per delete so that we don't blow up if a deletion fails.
        with get_session_with_current_tenant() as db_session:
            try:
                delete_chat_session(
                    user_id,
                    session_id,
                    db_session,
                    include_deleted=True,
                    hard_delete=True,
                )
            except Exception:
                logger.exception(
                    "delete_chat_session exceptioned. "
                    f"user_id={user_id} session_id={session_id}"
                )


#####
# Periodic Tasks
#####


@celery_app.task(
    name="check_ttl_management_task",
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def check_ttl_management_task(*, tenant_id: str) -> None:
    """Runs periodically to check if any ttl tasks should be run and adds them
    to the queue"""

    settings = load_settings()
    retention_limit_days = settings.maximum_chat_retention_days
    with get_session_with_current_tenant() as db_session:
        if should_perform_chat_ttl_check(retention_limit_days, db_session):
            perform_ttl_management_task.apply_async(
                kwargs=dict(
                    retention_limit_days=retention_limit_days, tenant_id=tenant_id
                ),
            )


#####
# Non-Periodic Tasks
#####


@celery_app.task(
    name="autogenerate_usage_report_task",
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def autogenerate_usage_report_task(*, tenant_id: str) -> None:
    """This generates usage report under the /admin/generate-usage/report endpoint"""
    with get_session_with_current_tenant() as db_session:
        create_new_usage_report(
            db_session=db_session,
            user_id=None,
            period=None,
        )


@build_celery_task_wrapper(name_query_history_report_task)
@celery_app.task(
    name="query_history_report_task",
    bind=True,
    # ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def query_history_report_task(self: Task, *, start: datetime, end: datetime) -> str:
    with get_session_with_current_tenant() as db_session:
        return query_history_report(
            db_session=db_session, request_id=self.request.id, start=start, end=end
        )
