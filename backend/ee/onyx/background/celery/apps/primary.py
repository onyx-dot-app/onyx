from ee.onyx.background.celery_utils import should_perform_chat_ttl_check
from ee.onyx.background.task_name_builders import name_chat_ttl_task
from ee.onyx.server.reporting.usage_export_generation import create_new_usage_report
from onyx.background.celery.apps.primary import celery_app
from onyx.background.task_utils import build_celery_task_wrapper
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.db.chat import delete_chat_sessions_older_than
from onyx.db.engine import get_session_with_tenant
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

# mark as EE for all tasks in this file


@build_celery_task_wrapper(name_chat_ttl_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def perform_ttl_management_task(
    retention_limit_days: int, *, tenant_id: str | None
) -> None:
    with get_session_with_tenant(tenant_id) as db_session:
        delete_chat_sessions_older_than(retention_limit_days, db_session)


#####
# Periodic Tasks
#####


@celery_app.task(
    name="check_ttl_management_task",
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def check_ttl_management_task(*, tenant_id: str | None) -> None:
    """Runs periodically to check if any ttl tasks should be run and adds them
    to the queue"""
    token = None
    if MULTI_TENANT and tenant_id is not None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    settings = load_settings()
    retention_limit_days = settings.maximum_chat_retention_days
    with get_session_with_tenant(tenant_id) as db_session:
        if should_perform_chat_ttl_check(retention_limit_days, db_session):
            perform_ttl_management_task.apply_async(
                kwargs=dict(
                    retention_limit_days=retention_limit_days, tenant_id=tenant_id
                ),
            )
    if token is not None:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@celery_app.task(
    name="autogenerate_usage_report_task",
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def autogenerate_usage_report_task(*, tenant_id: str | None) -> None:
    """This generates usage report under the /admin/generate-usage/report endpoint"""
    with get_session_with_tenant(tenant_id) as db_session:
        create_new_usage_report(
            db_session=db_session,
            user_id=None,
            period=None,
        )
