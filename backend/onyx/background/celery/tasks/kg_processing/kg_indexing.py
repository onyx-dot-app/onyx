from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.apps.client import celery_app
from onyx.background.celery.tasks.kg_processing.utils import (
    is_kg_processing_requirements_met,
)
from onyx.background.celery.tasks.kg_processing.utils import (
    is_kg_processing_unblocked,
)
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine import get_session_with_current_tenant


def try_creating_kg_processing_task(
    tenant_id: str,
) -> None:
    """Checks for any conditions that should block the KG processing task from being
    created, then creates the task.

    Does not check for scheduling related conditions as this function
    is used to trigger processing immediately.
    """

    try:

        with get_session_with_current_tenant() as db_session:
            if not is_kg_processing_requirements_met(db_session):
                return None

        # Send the KG processing task
        result = celery_app.send_task(
            OnyxCeleryTask.KG_PROCESSING,
            kwargs=dict(
                tenant_id=tenant_id,
            ),
            queue=OnyxCeleryQueues.KG_PROCESSING,
            priority=OnyxCeleryPriority.MEDIUM,
        )

        if not result:
            raise RuntimeError("send_task for kg processing failed.")

    except Exception:
        task_logger.exception(
            f"try_creating_kg_processing_task - Unexpected exception for tenant={tenant_id}"
        )

    return


def try_creating_kg_source_reset_task(
    tenant_id: str,
    source_name: str | None,
    index_name: str,
) -> str | None:
    """Checks for any conditions that should block the KG source reset task from being
    created, then creates the task.

    """

    try:

        # if blocked - return None
        with get_session_with_current_tenant() as db_session:
            if not is_kg_processing_unblocked(db_session):
                return None

        # Send the KG source reset task
        result = celery_app.send_task(
            OnyxCeleryTask.KG_RESET_SOURCE_INDEX,
            kwargs=dict(
                tenant_id=tenant_id,
                source_name=source_name,
                index_name=index_name,
            ),
            queue=OnyxCeleryQueues.KG_PROCESSING,
            priority=OnyxCeleryPriority.MEDIUM,
        )

        if not result:
            raise RuntimeError("send_task for kg source reset failed.")

    except Exception:
        task_logger.exception(
            f"try_creating_kg_source_reset_task - Unexpected exception for tenant={tenant_id}"
        )

    return None
