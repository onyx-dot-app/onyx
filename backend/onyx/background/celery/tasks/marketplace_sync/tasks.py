from uuid import UUID

from celery import Task, shared_task

from onyx.configs.constants import OnyxCeleryTask
from onyx.skills.marketplace.sync import (
    SYNC_LOCK_TIMEOUT_SECONDS,
    run_marketplace_sync,
)


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.SYNC_MARKETPLACE,
    soft_time_limit=SYNC_LOCK_TIMEOUT_SECONDS,
    bind=True,
    ignore_result=True,
)
def sync_marketplace_task(
    self: Task,  # noqa: ARG001
    *,
    marketplace_id: str,
    tenant_id: str,  # noqa: ARG001
) -> None:
    """Sync one GitHub marketplace (``onyx.skills.marketplace.sync``)."""
    run_marketplace_sync(UUID(marketplace_id))
