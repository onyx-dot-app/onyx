from celery import shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.skill_version import delete_orphan_skill_bundles
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_ORPHAN_SKILL_BUNDLE_CLEANUP,
    soft_time_limit=300,
    ignore_result=True,
)
def check_for_orphan_skill_bundle_cleanup(*, tenant_id: str) -> None:
    """Retry deletion of orphan skill bundles in the specified tenant."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        deleted = delete_orphan_skill_bundles()
        if deleted:
            task_logger.info(
                f"Deleted {deleted} orphan skill bundle file(s) (tenant {tenant_id})."
            )
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
