from datetime import timedelta

from sqlalchemy.orm import Session

from danswer.background.celery.celery_app import celery_app
from danswer.background.task_utils import build_celery_task_wrapper
from danswer.configs.app_configs import JOB_TIMEOUT
from danswer.db.chat import delete_chat_sessions_older_than
from danswer.db.engine import get_sqlalchemy_engine
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

logger = setup_logger()

# mark as EE for all tasks in this file
global_version.set_ee()


@build_celery_task_wrapper(name_sync_external_doc_permissions_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def sync_external_doc_permissions_task(cc_pair_id: int) -> None:
    with Session(get_sqlalchemy_engine()) as db_session:
        run_external_doc_permission_sync(db_session=db_session, cc_pair_id=cc_pair_id)


@build_celery_task_wrapper(name_sync_external_group_permissions_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def sync_external_group_permissions_task(cc_pair_id: int) -> None:
    with Session(get_sqlalchemy_engine()) as db_session:
        run_external_group_permission_sync(db_session=db_session, cc_pair_id=cc_pair_id)


@build_celery_task_wrapper(name_chat_ttl_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def perform_ttl_management_task(retention_limit_days: int) -> None:
    with Session(get_sqlalchemy_engine()) as db_session:
        delete_chat_sessions_older_than(retention_limit_days, db_session)


#####
# Periodic Tasks
#####
@celery_app.task(
    name="check_sync_external_doc_permissions_task",
    soft_time_limit=JOB_TIMEOUT,
)
def check_sync_external_doc_permissions_task() -> None:
    """Runs periodically to sync external permissions"""
    with Session(get_sqlalchemy_engine()) as db_session:
        cc_pairs = get_all_auto_sync_cc_pairs(db_session)
        for cc_pair in cc_pairs:
            if should_perform_external_doc_permissions_check(
                cc_pair=cc_pair, db_session=db_session
            ):
                sync_external_doc_permissions_task.apply_async(
                    kwargs=dict(cc_pair_id=cc_pair.id),
                )


@celery_app.task(
    name="check_sync_external_group_permissions_task",
    soft_time_limit=JOB_TIMEOUT,
)
def check_sync_external_group_permissions_task() -> None:
    """Runs periodically to sync external group permissions"""
    with Session(get_sqlalchemy_engine()) as db_session:
        cc_pairs = get_all_auto_sync_cc_pairs(db_session)
        for cc_pair in cc_pairs:
            if should_perform_external_group_permissions_check(
                cc_pair=cc_pair, db_session=db_session
            ):
                sync_external_group_permissions_task.apply_async(
                    kwargs=dict(cc_pair_id=cc_pair.id),
                )


@celery_app.task(
    name="check_ttl_management_task",
    soft_time_limit=JOB_TIMEOUT,
)
def check_ttl_management_task() -> None:
    """Runs periodically to check if any ttl tasks should be run and adds them
    to the queue"""
    settings = load_settings()
    retention_limit_days = settings.maximum_chat_retention_days
    with Session(get_sqlalchemy_engine()) as db_session:
        if should_perform_chat_ttl_check(retention_limit_days, db_session):
            perform_ttl_management_task.apply_async(
                kwargs=dict(retention_limit_days=retention_limit_days),
            )


@celery_app.task(
    name="autogenerate_usage_report_task",
    soft_time_limit=JOB_TIMEOUT,
)
def autogenerate_usage_report_task() -> None:
    """This generates usage report under the /admin/generate-usage/report endpoint"""
    with Session(get_sqlalchemy_engine()) as db_session:
        create_new_usage_report(
            db_session=db_session,
            user_id=None,
            period=None,
        )


#####
# Celery Beat (Periodic Tasks) Settings
#####
celery_app.conf.beat_schedule = {
    "sync-external-doc-permissions": {
        "task": "check_sync_external_doc_permissions_task",
        "schedule": timedelta(seconds=5),  # TODO: optimize this
    },
    "sync-external-group-permissions": {
        "task": "check_sync_external_group_permissions_task",
        "schedule": timedelta(seconds=5),  # TODO: optimize this
    },
    "autogenerate_usage_report": {
        "task": "autogenerate_usage_report_task",
        "schedule": timedelta(days=30),  # TODO: change this to config flag
    },
    "check-ttl-management": {
        "task": "check_ttl_management_task",
        "schedule": timedelta(hours=1),
    },
    **(celery_app.conf.beat_schedule or {}),
}
