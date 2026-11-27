from uuid import UUID

from celery import Celery

from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryQueues, OnyxCeleryTask
from onyx.server.features.build.timeouts import SCHEDULED_RUN_QUEUE_RESIDENCY_SECONDS


def send_scheduled_run(app: Celery, run_id: UUID, tenant_id: str) -> None:
    """Send a QUEUED run to the executor. The message expires with the queue
    residency limit, the age at which the stuck-run sweeper fails the run."""
    app.send_task(
        OnyxCeleryTask.SCHEDULED_TASKS_RUN,
        kwargs={"run_id": str(run_id), "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.SCHEDULED_TASKS,
        priority=OnyxCeleryPriority.MEDIUM,
        expires=SCHEDULED_RUN_QUEUE_RESIDENCY_SECONDS,
    )
