from celery import shared_task
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.app_configs import JOB_TIMEOUT
from celery import Task


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_DOC_PERMISSIONS_SYNC,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
)
def check_for_doc_permissions_sync(self: Task, *, tenant_id: str) -> bool | None:
    # override of tasks in ee/light to avoid errors in background worker due to wrongly registered tasks
    pass


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_EXTERNAL_GROUP_SYNC,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
)
def check_for_external_group_sync(self: Task, *, tenant_id: str) -> bool | None:
    pass
