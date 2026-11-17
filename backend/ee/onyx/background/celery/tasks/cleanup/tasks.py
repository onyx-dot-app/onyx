from celery import shared_task

from ee.onyx.background.task_name_builders import QUERY_HISTORY_TASK_NAME_PREFIX
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import (
    USER_EXPORT_TASK_EXPIRES,
    USER_JOB_LOST_TASK_GRACE,
    OnyxCeleryTask,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.tasks import cleanup_stale_tasks


@shared_task(
    name=OnyxCeleryTask.EXPORT_QUERY_HISTORY_CLEANUP_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def export_query_history_cleanup_task(*, tenant_id: str) -> None:
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        cleanup_stale_tasks(
            db_session,
            QUERY_HISTORY_TASK_NAME_PREFIX,
            pending_timeout=USER_EXPORT_TASK_EXPIRES + USER_JOB_LOST_TASK_GRACE,
            started_timeout=JOB_TIMEOUT + USER_JOB_LOST_TASK_GRACE,
        )
