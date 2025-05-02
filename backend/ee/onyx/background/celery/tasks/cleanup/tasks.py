from celery import shared_task

from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.utils.logger import setup_logger


logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.EXPORT_QUERY_HISTORY_CLEANUP_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def export_query_history_cleanup_task(*, tenant_id: str) -> None:
    logger.error("!" * 80)
