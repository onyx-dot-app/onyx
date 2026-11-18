from celery import shared_task

from ee.onyx.background.task_name_builders import QUERY_HISTORY_TASK_NAME_PREFIX
from onyx.background.task_utils import construct_query_history_report_name
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import (
    USER_EXPORT_TASK_EXPIRES,
    USER_JOB_LOST_TASK_GRACE,
    OnyxCeleryTask,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.tasks import cleanup_stale_tasks, get_expired_failed_task_ids
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.EXPORT_QUERY_HISTORY_CLEANUP_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def export_query_history_cleanup_task(*, tenant_id: str) -> None:
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        expired = get_expired_failed_task_ids(
            db_session, QUERY_HISTORY_TASK_NAME_PREFIX
        )
        # End the read, so no transaction stays open during file deletes.
        db_session.commit()
        # A worker that stopped after its upload leaves an unpublished file.
        # Purge a failure only after its file is gone: the row hides the file.
        file_store = get_default_file_store()
        deleted: list[str] = []
        for task_id in expired:
            try:
                file_store.delete_file(
                    construct_query_history_report_name(task_id),
                    error_on_missing=False,
                )
            except Exception:
                logger.exception(
                    "Failed to delete the file of failed export %s", task_id
                )
                continue
            deleted.append(task_id)
        cleanup_stale_tasks(
            db_session,
            QUERY_HISTORY_TASK_NAME_PREFIX,
            pending_timeout=USER_EXPORT_TASK_EXPIRES + USER_JOB_LOST_TASK_GRACE,
            started_timeout=JOB_TIMEOUT + USER_JOB_LOST_TASK_GRACE,
            expired_failed_task_ids=deleted,
        )
        # Usage reports list report rows, not files, so no file can leak.
        cleanup_stale_tasks(
            db_session,
            OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK,
            pending_timeout=USER_EXPORT_TASK_EXPIRES + USER_JOB_LOST_TASK_GRACE,
            started_timeout=JOB_TIMEOUT + USER_JOB_LOST_TASK_GRACE,
            expired_failed_task_ids=get_expired_failed_task_ids(
                db_session, OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK
            ),
        )
