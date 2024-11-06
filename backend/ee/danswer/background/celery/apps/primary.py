from danswer.background.celery.apps.primary import celery_app
from danswer.background.task_utils import build_celery_task_wrapper
from danswer.configs.app_configs import JOB_TIMEOUT
from danswer.configs.app_configs import MULTI_TENANT
from danswer.db.chat import delete_chat_sessions_older_than
from danswer.db.engine import get_session_with_tenant
from danswer.server.settings.store import load_settings
from danswer.utils.logger import setup_logger
from danswer.utils.variable_functionality import global_version
from ee.danswer.background.celery_utils import should_perform_chat_ttl_check
from ee.danswer.background.celery_utils import (
    should_perform_external_doc_permissions_check,
)
from ee.danswer.background.celery_utils import (
    should_perform_external_group_permissions_check,
)
from ee.danswer.background.task_name_builders import name_chat_ttl_task
from ee.danswer.background.task_name_builders import (
    name_sync_external_doc_permissions_task,
)
from ee.danswer.background.task_name_builders import (
    name_sync_external_group_permissions_task,
)
from ee.danswer.db.connector_credential_pair import get_all_auto_sync_cc_pairs
from ee.danswer.external_permissions.permission_sync import (
    run_external_doc_permission_sync,
)
from ee.danswer.external_permissions.permission_sync import (
    run_external_group_permission_sync,
)
from ee.danswer.server.reporting.usage_export_generation import create_new_usage_report
from shared_configs.configs import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

# mark as EE for all tasks in this file
global_version.set_ee()


@build_celery_task_wrapper(name_sync_external_doc_permissions_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def sync_external_doc_permissions_task(
    cc_pair_id: int, *, tenant_id: str | None
) -> None:
    with get_session_with_tenant(tenant_id) as db_session:
        run_external_doc_permission_sync(db_session=db_session, cc_pair_id=cc_pair_id)


@build_celery_task_wrapper(name_sync_external_group_permissions_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def sync_external_group_permissions_task(
    cc_pair_id: int, *, tenant_id: str | None
) -> None:
    with get_session_with_tenant(tenant_id) as db_session:
        run_external_group_permission_sync(db_session=db_session, cc_pair_id=cc_pair_id)


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
    name="check_sync_external_doc_permissions_task",
    soft_time_limit=JOB_TIMEOUT,
)
def check_sync_external_doc_permissions_task(*, tenant_id: str | None) -> None:
    """Runs periodically to sync external permissions"""
    with get_session_with_tenant(tenant_id) as db_session:
        cc_pairs = get_all_auto_sync_cc_pairs(db_session)
        for cc_pair in cc_pairs:
            if should_perform_external_doc_permissions_check(
                cc_pair=cc_pair, db_session=db_session
            ):
                sync_external_doc_permissions_task.apply_async(
                    kwargs=dict(cc_pair_id=cc_pair.id, tenant_id=tenant_id),
                )


@celery_app.task(
    name="check_sync_external_group_permissions_task",
    soft_time_limit=JOB_TIMEOUT,
)
def check_sync_external_group_permissions_task(*, tenant_id: str | None) -> None:
    """Runs periodically to sync external group permissions"""
    with get_session_with_tenant(tenant_id) as db_session:
        cc_pairs = get_all_auto_sync_cc_pairs(db_session)
        for cc_pair in cc_pairs:
            if should_perform_external_group_permissions_check(
                cc_pair=cc_pair, db_session=db_session
            ):
                sync_external_group_permissions_task.apply_async(
                    kwargs=dict(cc_pair_id=cc_pair.id, tenant_id=tenant_id),
                )


@celery_app.task(
    name="check_ttl_management_task",
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
