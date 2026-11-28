from uuid import UUID

from celery import Celery

from onyx.configs.constants import (
    NotificationType,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.scheduled_task import (
    fail_queued_run__no_commit,
    notify_run_owner__no_commit,
)
from onyx.server.features.build.timeouts import SCHEDULED_RUN_QUEUE_RESIDENCY_SECONDS
from onyx.utils.logger import setup_logger

logger = setup_logger()


def send_scheduled_run(app: Celery, run_id: UUID, tenant_id: str) -> bool:
    """Send a committed QUEUED run to the executor. The message expires with
    the queue residency limit, the age at which the stuck-run sweeper fails
    the run.

    A run that cannot be sent fails at once and its owner is notified, so it
    does not block the next runs of its task. Returns whether it was sent."""
    try:
        app.send_task(
            OnyxCeleryTask.SCHEDULED_TASKS_RUN,
            kwargs={"run_id": str(run_id), "tenant_id": tenant_id},
            queue=OnyxCeleryQueues.SCHEDULED_TASKS,
            priority=OnyxCeleryPriority.MEDIUM,
            expires=SCHEDULED_RUN_QUEUE_RESIDENCY_SECONDS,
        )
        return True
    except Exception:
        logger.exception("Could not send scheduled run %s", run_id)
    with get_session_with_current_tenant() as db_session:
        run = fail_queued_run__no_commit(
            db_session=db_session,
            run_id=run_id,
            error_detail="The run could not be sent to a worker",
        )
        if run is not None:
            notify_run_owner__no_commit(
                db_session, run, NotificationType.SCHEDULED_TASK_FAILED
            )
        db_session.commit()
    return False
