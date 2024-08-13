from datetime import timedelta
from typing import Any

from celery.signals import beat_init
from celery.signals import worker_init
from sqlalchemy.orm import Session

from danswer.background.celery.celery_app import celery_app
from danswer.background.task_utils import build_celery_task_wrapper
from danswer.configs.app_configs import JOB_TIMEOUT
from danswer.configs.constants import POSTGRES_CELERY_BEAT_APP_NAME
from danswer.configs.constants import POSTGRES_CELERY_WORKER_APP_NAME
from danswer.db.chat import delete_chat_sessions_older_than
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.engine import init_sqlalchemy_engine
from danswer.server.settings.store import load_settings
from danswer.utils.logger import setup_logger
from danswer.utils.variable_functionality import global_version
from ee.danswer.background.celery_utils import should_perform_chat_ttl_check
from ee.danswer.background.celery_utils import should_sync_user_groups
from ee.danswer.background.task_name_builders import name_chat_ttl_task
from ee.danswer.background.task_name_builders import name_user_group_sync_task
from ee.danswer.db.user_group import fetch_user_groups
from ee.danswer.server.reporting.usage_export_generation import create_new_usage_report
from ee.danswer.user_groups.sync import sync_user_groups

logger = setup_logger()

# mark as EE for all tasks in this file
global_version.set_ee()


@build_celery_task_wrapper(name_user_group_sync_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def sync_user_group_task(user_group_id: int) -> None:
    with Session(get_sqlalchemy_engine()) as db_session:
        # actual sync logic
        try:
            sync_user_groups(user_group_id=user_group_id, db_session=db_session)
        except Exception as e:
            logger.exception(f"Failed to sync user group - {e}")


@build_celery_task_wrapper(name_chat_ttl_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def perform_ttl_management_task(retention_limit_days: int) -> None:
    with Session(get_sqlalchemy_engine()) as db_session:
        delete_chat_sessions_older_than(retention_limit_days, db_session)


#####
# Periodic Tasks
#####


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
    name="check_for_user_groups_sync_task",
    soft_time_limit=JOB_TIMEOUT,
)
def check_for_user_groups_sync_task() -> None:
    """Runs periodically to check if any user groups are out of sync
    Creates a task to sync the user group if needed"""
    with Session(get_sqlalchemy_engine()) as db_session:
        # check if any document sets are not synced
        user_groups = fetch_user_groups(db_session=db_session, only_current=False)
        for user_group in user_groups:
            if should_sync_user_groups(user_group, db_session):
                logger.info(f"User Group {user_group.id} is not synced. Syncing now!")
                sync_user_group_task.apply_async(
                    kwargs=dict(user_group_id=user_group.id),
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


@beat_init.connect
def on_beat_init(sender: Any, **kwargs: Any) -> None:
    init_sqlalchemy_engine(POSTGRES_CELERY_BEAT_APP_NAME)


@worker_init.connect
def on_worker_init(sender: Any, **kwargs: Any) -> None:
    init_sqlalchemy_engine(POSTGRES_CELERY_WORKER_APP_NAME)


#####
# Celery Beat (Periodic Tasks) Settings
#####
celery_app.conf.beat_schedule = {
    "check-for-user-group-sync": {
        "task": "check_for_user_groups_sync_task",
        "schedule": timedelta(seconds=5),
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
