from datetime import datetime
from datetime import timezone

from celery import shared_task
from celery import Task
from redis import Redis

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.vespa.tasks import celery_get_queue_length
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType


def _collect_queue_metrics(r_celery: Redis) -> dict[str, int]:
    """Collect metrics about queue lengths for different Celery queues"""
    return {
        "celery": celery_get_queue_length("celery", r_celery),
        "indexing": celery_get_queue_length(
            OnyxCeleryQueues.CONNECTOR_INDEXING, r_celery
        ),
        "sync": celery_get_queue_length(OnyxCeleryQueues.VESPA_METADATA_SYNC, r_celery),
        "deletion": celery_get_queue_length(
            OnyxCeleryQueues.CONNECTOR_DELETION, r_celery
        ),
        "pruning": celery_get_queue_length(
            OnyxCeleryQueues.CONNECTOR_PRUNING, r_celery
        ),
        "permissions_sync": celery_get_queue_length(
            OnyxCeleryQueues.CONNECTOR_DOC_PERMISSIONS_SYNC, r_celery
        ),
        "external_group_sync": celery_get_queue_length(
            OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC, r_celery
        ),
        "permissions_upsert": celery_get_queue_length(
            OnyxCeleryQueues.DOC_PERMISSIONS_UPSERT, r_celery
        ),
    }


@shared_task(
    name=OnyxCeleryTask.MONITOR_BACKGROUND_PROCESSES,
    soft_time_limit=JOB_TIMEOUT,
    queue="monitoring",
    bind=True,
)
def monitor_background_processes(self: Task, *, tenant_id: str | None) -> None:
    """Collect and emit metrics about background processes.
    This task runs periodically to gather metrics about:
    - Queue lengths for different Celery queues
    - Worker status and task counts
    - Memory usage
    - Task latencies
    """
    task_logger.info("Starting background process monitoring")

    try:
        # Get Redis client for Celery broker
        r_celery = self.app.broker_connection().channel().client  # type: ignore

        # Collect queue metrics
        queue_metrics = _collect_queue_metrics(r_celery)
        task_logger.info(f"Queue metrics: {queue_metrics}")

        # Emit metrics via telemetry
        metrics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "queues": queue_metrics,
        }

        optional_telemetry(
            record_type=RecordType.USAGE,
            data={"background_metrics": metrics},
        )

        task_logger.info("Successfully emitted background process metrics")

    except Exception as e:
        task_logger.exception("Error collecting background process metrics")
        raise e
