from celery import shared_task

from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.hook import cleanup_old_execution_logs__no_commit
from onyx.utils.logger import setup_logger

logger = setup_logger()

_HOOK_EXECUTION_LOG_RETENTION_DAYS: int = 30


@shared_task(
    name=OnyxCeleryTask.HOOK_EXECUTION_LOG_CLEANUP_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    trail=False,
)
def hook_execution_log_cleanup_task(*, tenant_id: str) -> None:  # noqa: ARG001
    try:
        with get_session_with_current_tenant() as db_session:
            deleted: int = cleanup_old_execution_logs__no_commit(
                db_session=db_session,
                max_age_days=_HOOK_EXECUTION_LOG_RETENTION_DAYS,
            )
            db_session.commit()
            if deleted:
                logger.info(
                    f"Deleted {deleted} hook execution log(s) older than "
                    f"{_HOOK_EXECUTION_LOG_RETENTION_DAYS} days."
                )
    except Exception:
        logger.exception("Failed to clean up hook execution logs")
        raise
