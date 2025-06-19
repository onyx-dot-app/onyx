from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.apps.client import celery_app
from onyx.background.celery.tasks.kg_processing.utils import is_kg_processing_blocked
from onyx.background.celery.tasks.kg_processing.utils import (
    is_kg_processing_requirements_met,
)
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask


def try_creating_kg_processing_task(
    tenant_id: str,
) -> bool:
    """Schedules the KG Processing for a tenant immediately. Will not schedule if
    the tenant is not ready for KG processing.
    """

    try:
        if not is_kg_processing_requirements_met():
            return False

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
            task_logger.error("send_task for kg processing failed.")
        return bool(result)

    except Exception:
        task_logger.exception(
            f"try_creating_kg_processing_task - Unexpected exception for tenant={tenant_id}"
        )
        return False


def try_creating_kg_source_reset_task(
    tenant_id: str,
    source_name: str | None,
    index_name: str,
) -> bool:
    """Schedules the KG Source Reset for a tenant immediately. Will not do anything if
    the tenant is currently being processed.
    """

    try:
        if is_kg_processing_blocked():
            return False

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
            task_logger.error("send_task for kg source reset failed.")
        return bool(result)

    except Exception:
        task_logger.exception(
            f"try_creating_kg_source_reset_task - Unexpected exception for tenant={tenant_id}"
        )
        return False
