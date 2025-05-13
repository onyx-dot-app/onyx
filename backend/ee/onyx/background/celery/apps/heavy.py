import csv
import io
from datetime import datetime
from datetime import timezone

from celery import shared_task
from celery import Task

from ee.onyx.background.task_name_builders import query_history_task_name
from ee.onyx.server.query_history.api import fetch_and_process_chat_session_history
from ee.onyx.server.query_history.api import ONYX_ANONYMIZED_EMAIL
from ee.onyx.server.query_history.models import ChatSessionSnapshot
from ee.onyx.server.query_history.models import QuestionAnswerPairSnapshot
from onyx.background.celery.apps.heavy import celery_app
from onyx.background.task_utils import construct_query_history_report_name
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.app_configs import ONYX_QUERY_HISTORY_TYPE
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import FileType
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import QueryHistoryType
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.enums import TaskStatus
from onyx.db.tasks import delete_task_with_id
from onyx.db.tasks import mark_task_as_finished_with_id
from onyx.db.tasks import register_task
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger


logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.EXPORT_QUERY_HISTORY_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def export_query_history_task(self: Task, *, start: datetime, end: datetime) -> None:
    if not self.request.id:
        raise RuntimeError("No task id defined for this task; cannot identify it")

    task_id = self.request.id
    start_time = datetime.now(tz=timezone.utc)

    with get_session_with_current_tenant() as db_session:
        try:
            register_task(
                db_session=db_session,
                task_name=query_history_task_name(start=start, end=end),
                task_id=task_id,
                status=TaskStatus.STARTED,
                start_time=start_time,
            )

            complete_chat_session_history: list[ChatSessionSnapshot] = (
                fetch_and_process_chat_session_history(
                    db_session=db_session,
                    start=start,
                    end=end,
                    feedback_type=None,
                    limit=None,
                )
            )
        except Exception:
            logger.exception(f"Failed to export query history with {task_id=}")
            mark_task_as_finished_with_id(
                db_session=db_session,
                task_id=task_id,
                success=False,
            )
            raise

    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
        complete_chat_session_history = [
            ChatSessionSnapshot(
                **chat_session_snapshot.model_dump(), user_email=ONYX_ANONYMIZED_EMAIL
            )
            for chat_session_snapshot in complete_chat_session_history
        ]

    qa_pairs: list[QuestionAnswerPairSnapshot] = [
        qa_pair
        for chat_session_snapshot in complete_chat_session_history
        for qa_pair in QuestionAnswerPairSnapshot.from_chat_session_snapshot(
            chat_session_snapshot
        )
    ]

    stream = io.StringIO()
    writer = csv.DictWriter(
        stream,
        fieldnames=list(QuestionAnswerPairSnapshot.model_fields.keys()),
    )
    writer.writeheader()
    for row in qa_pairs:
        writer.writerow(row.to_json())

    report_name = construct_query_history_report_name(task_id)
    with get_session_with_current_tenant() as db_session:
        try:
            stream.seek(0)
            get_default_file_store(db_session).save_file(
                file_name=report_name,
                content=stream,
                display_name=report_name,
                file_origin=FileOrigin.QUERY_HISTORY_CSV,
                file_type=FileType.CSV,
                file_metadata={
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "start_time": start_time.isoformat(),
                },
            )

            delete_task_with_id(
                db_session=db_session,
                task_id=task_id,
            )
        except Exception:
            logger.exception(
                f"Failed to save query history export file; {report_name=}"
            )
            mark_task_as_finished_with_id(
                db_session=db_session,
                task_id=task_id,
                success=False,
            )
            raise


celery_app.autodiscover_tasks(
    [
        "ee.onyx.background.celery.tasks.doc_permission_syncing",
        "ee.onyx.background.celery.tasks.external_group_syncing",
        "ee.onyx.background.celery.tasks.cleanup",
    ]
)
