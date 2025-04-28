import csv
import io
from datetime import datetime

from celery.app.task import Task

from ee.onyx.background.celery_utils import should_perform_chat_ttl_check
from ee.onyx.background.task_name_builders import name_chat_ttl_task
from ee.onyx.server.query_history.models import ChatSessionSnapshot
from ee.onyx.server.query_history.models import QuestionAnswerPairSnapshot
from ee.onyx.server.reporting.usage_export_generation import create_new_usage_report
from onyx.background.celery.apps.primary import celery_app
from onyx.background.task_utils import build_celery_task_wrapper
from onyx.background.task_utils import query_history_report_name
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.app_configs import ONYX_QUERY_HISTORY_TYPE
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import QueryHistoryType
from onyx.db.chat import delete_chat_session
from onyx.db.chat import get_chat_sessions_older_than
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.enums import TaskStatus
from onyx.db.tasks import mark_task_as_finished_with_id
from onyx.db.tasks import register_task
from onyx.file_store.file_store import get_default_file_store
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger

logger = setup_logger()

# mark as EE for all tasks in this file


@build_celery_task_wrapper(name_chat_ttl_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def perform_ttl_management_task(retention_limit_days: int, *, tenant_id: str) -> None:
    with get_session_with_current_tenant() as db_session:
        old_chat_sessions = get_chat_sessions_older_than(
            retention_limit_days, db_session
        )

    for user_id, session_id in old_chat_sessions:
        # one session per delete so that we don't blow up if a deletion fails.
        with get_session_with_current_tenant() as db_session:
            try:
                delete_chat_session(
                    user_id,
                    session_id,
                    db_session,
                    include_deleted=True,
                    hard_delete=True,
                )
            except Exception:
                logger.exception(
                    "delete_chat_session exceptioned. "
                    f"user_id={user_id} session_id={session_id}"
                )


#####
# Periodic Tasks
#####


@celery_app.task(
    name=OnyxCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def check_ttl_management_task(*, tenant_id: str) -> None:
    """Runs periodically to check if any ttl tasks should be run and adds them
    to the queue"""

    settings = load_settings()
    retention_limit_days = settings.maximum_chat_retention_days
    with get_session_with_current_tenant() as db_session:
        if should_perform_chat_ttl_check(retention_limit_days, db_session):
            perform_ttl_management_task.apply_async(
                kwargs=dict(
                    retention_limit_days=retention_limit_days, tenant_id=tenant_id
                ),
            )


@celery_app.task(
    name=OnyxCeleryTask.AUTOGENERATE_USAGE_REPORT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def autogenerate_usage_report_task(*, tenant_id: str) -> None:
    """This generates usage report under the /admin/generate-usage/report endpoint"""
    with get_session_with_current_tenant() as db_session:
        create_new_usage_report(
            db_session=db_session,
            user_id=None,
            period=None,
        )


@celery_app.task(
    name=OnyxCeleryTask.EXPORT_QUERY_HISTORY_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
)
def export_query_history_task(self: Task, *, start: datetime, end: datetime) -> None:
    # Importing here because importing in the global namespace causes a circular dependency issue.
    from ee.onyx.server.query_history.api import fetch_and_process_chat_session_history
    from ee.onyx.server.query_history.api import ONYX_ANONYMIZED_EMAIL

    if not self.request.id:
        raise RuntimeError("No task id defined for this task; cannot identify it")

    task_id = self.request.id

    with get_session_with_current_tenant() as db_session:
        register_task(
            db_session=db_session,
            task_name=f"{OnyxCeleryTask.EXPORT_QUERY_HISTORY_TASK}_{start}_{end}",
            task_id=task_id,
            status=TaskStatus.STARTED,
        )

        complete_chat_session_history = fetch_and_process_chat_session_history(
            db_session=db_session,
            start=start,
            end=end,
            feedback_type=None,
            limit=None,
        )

        def to_qa_pair(
            chat_session_snapshot: ChatSessionSnapshot,
        ) -> list[QuestionAnswerPairSnapshot]:
            if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
                chat_session_snapshot.user_email = ONYX_ANONYMIZED_EMAIL
            return QuestionAnswerPairSnapshot.from_chat_session_snapshot(
                chat_session_snapshot
            )

        qa_pairs: list[QuestionAnswerPairSnapshot] = [
            qa_pair
            for chat_session_snapshot in complete_chat_session_history
            for qa_pair in to_qa_pair(chat_session_snapshot)
        ]

        report_name = query_history_report_name(task_id)

        file_store = get_default_file_store(db_session)
        stream = io.StringIO()
        writer = csv.DictWriter(
            stream, fieldnames=list(QuestionAnswerPairSnapshot.model_fields.keys())
        )

        writer.writeheader()
        for row in qa_pairs:
            writer.writerow(row.to_json())

        stream.seek(0)
        file_store.save_file(
            file_name=report_name,
            content=stream,
            display_name=report_name,
            file_origin=FileOrigin.GENERATED_REPORT,
            file_type="text/csv",
        )

        mark_task_as_finished_with_id(
            db_session=db_session,
            task_id=task_id,
        )
