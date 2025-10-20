import uuid
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ee.onyx.background.task_name_builders import query_history_task_name
from ee.onyx.db.query_history import get_all_query_history_export_tasks
from ee.onyx.db.query_history import get_page_of_chat_sessions
from ee.onyx.db.query_history import get_total_filtered_chat_sessions_count
from ee.onyx.server.query_history.models import ChatSessionMinimal
from ee.onyx.server.query_history.models import ChatSessionSnapshot
from ee.onyx.server.query_history.models import MessageSnapshot
from ee.onyx.server.query_history.models import QueryHistoryExport
from onyx.auth.users import current_admin_user
from onyx.auth.users import get_display_email
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.background.task_utils import construct_query_history_report_name
from onyx.chat.chat_utils import create_chat_chain
from onyx.configs.app_configs import ONYX_QUERY_HISTORY_TYPE
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import FileType
from onyx.configs.constants import MessageType
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import QAFeedbackType
from onyx.configs.constants import QueryHistoryType
from onyx.configs.constants import SessionType
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_chat_sessions_by_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import TaskStatus
from onyx.db.file_record import get_query_history_export_files
from onyx.db.models import ChatSession
from onyx.db.models import User
from onyx.db.tasks import get_task_with_id
from onyx.db.tasks import register_task
from onyx.file_store.file_store import get_default_file_store
from onyx.server.documents.models import PaginatedReturn
from onyx.server.query_and_chat.models import ChatSessionDetails
from onyx.server.query_and_chat.models import ChatSessionsResponse
from onyx.utils.threadpool_concurrency import parallel_yield
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()

ONYX_ANONYMIZED_EMAIL = "anonymous@anonymous.invalid"


def ensure_query_history_is_enabled(
    disallowed: list[QueryHistoryType],
) -> None:
    if ONYX_QUERY_HISTORY_TYPE in disallowed:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )


def yield_snapshot_from_chat_session(
    chat_session: ChatSession,
    db_session: Session,
) -> Generator[ChatSessionSnapshot | None]:
    yield snapshot_from_chat_session(chat_session=chat_session, db_session=db_session)


def fetch_and_process_chat_session_history(
    db_session: Session,
    start: datetime,
    end: datetime,
    limit: int | None = 500,
) -> Generator[ChatSessionSnapshot]:
    PAGE_SIZE = 100

    page = 0
    while True:
        paged_chat_sessions = get_page_of_chat_sessions(
            start_time=start,
            end_time=end,
            db_session=db_session,
            page_num=page,
            page_size=PAGE_SIZE,
        )

        if not paged_chat_sessions:
            break

        paged_snapshots = parallel_yield(
            [
                yield_snapshot_from_chat_session(
                    db_session=db_session,
                    chat_session=chat_session,
                )
                for chat_session in paged_chat_sessions
            ]
        )

        for snapshot in paged_snapshots:
            if snapshot:
                yield snapshot

        # If we've fetched *less* than a `PAGE_SIZE` worth
        # of data, we have reached the end of the
        # pagination sequence; break.
        if len(paged_chat_sessions) < PAGE_SIZE:
            break

        page += 1


def snapshot_from_chat_session(
    chat_session: ChatSession,
    db_session: Session,
) -> ChatSessionSnapshot | None:
    try:
        # Older chats may not have the right structure
        last_message, messages = create_chat_chain(
            chat_session_id=chat_session.id, db_session=db_session
        )
        messages.append(last_message)
    except RuntimeError:
        return None

    flow_type = SessionType.SLACK if chat_session.onyxbot_flow else SessionType.CHAT

    return ChatSessionSnapshot(
        id=chat_session.id,
        user_email=get_display_email(
            chat_session.user.email if chat_session.user else None
        ),
        name=chat_session.description,
        messages=[
            MessageSnapshot.build(message)
            for message in messages
            if message.message_type != MessageType.SYSTEM
        ],
        assistant_id=chat_session.persona_id,
        assistant_name=chat_session.persona.name if chat_session.persona else None,
        time_created=chat_session.time_created,
        flow_type=flow_type,
    )


@router.get("/admin/chat-sessions")
def admin_get_chat_sessions(
    user_id: UUID,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionsResponse:
    # we specifically don't allow this endpoint if "anonymized" since
    # this is a direct query on the user id
    ensure_query_history_is_enabled(
        [
            QueryHistoryType.DISABLED,
            QueryHistoryType.ANONYMIZED,
        ]
    )

    try:
        chat_sessions = get_chat_sessions_by_user(
            user_id=user_id, deleted=False, db_session=db_session, limit=0
        )

    except ValueError:
        raise ValueError("Chat session does not exist or has been deleted")

    return ChatSessionsResponse(
        sessions=[
            ChatSessionDetails(
                id=chat.id,
                name=chat.description,
                persona_id=chat.persona_id,
                time_created=chat.time_created.isoformat(),
                time_updated=chat.time_updated.isoformat(),
                shared_status=chat.shared_status,
                current_alternate_model=chat.current_alternate_model,
            )
            for chat in chat_sessions
        ]
    )


@router.get("/admin/chat-session-history")
def get_chat_session_history(
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1),
    feedback_type: QAFeedbackType | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[ChatSessionMinimal]:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

    page_of_chat_sessions = get_page_of_chat_sessions(
        page_num=page_num,
        page_size=page_size,
        db_session=db_session,
        start_time=start_time,
        end_time=end_time,
        feedback_filter=feedback_type,
    )

    total_filtered_chat_sessions_count = get_total_filtered_chat_sessions_count(
        db_session=db_session,
        start_time=start_time,
        end_time=end_time,
        feedback_filter=feedback_type,
    )

    minimal_chat_sessions: list[ChatSessionMinimal] = []

    for chat_session in page_of_chat_sessions:
        minimal_chat_session = ChatSessionMinimal.from_chat_session(chat_session)
        if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
            minimal_chat_session.user_email = ONYX_ANONYMIZED_EMAIL
        minimal_chat_sessions.append(minimal_chat_session)

    return PaginatedReturn(
        items=minimal_chat_sessions,
        total_items=total_filtered_chat_sessions_count,
    )


@router.get("/admin/chat-session-history/{chat_session_id}")
def get_chat_session_admin(
    chat_session_id: UUID,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionSnapshot:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_session_id,
            user_id=None,  # view chat regardless of user
            db_session=db_session,
            include_deleted=True,
        )
    except ValueError:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            f"Chat session with id '{chat_session_id}' does not exist.",
        )
    snapshot = snapshot_from_chat_session(
        chat_session=chat_session, db_session=db_session
    )

    if snapshot is None:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            f"Could not create snapshot for chat session with id '{chat_session_id}'",
        )

    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
        snapshot.user_email = ONYX_ANONYMIZED_EMAIL

    return snapshot


@router.get("/admin/query-history/list")
def list_all_query_history_exports(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[QueryHistoryExport]:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])
    try:
        pending_tasks = [
            QueryHistoryExport.from_task(task)
            for task in get_all_query_history_export_tasks(db_session=db_session)
        ]
        generated_files = [
            QueryHistoryExport.from_file(file)
            for file in get_query_history_export_files(db_session=db_session)
        ]
        merged = pending_tasks + generated_files

        # We sort based off of the start-time of the task.
        # We also return it in reverse order since viewing generated reports in most-recent to least-recent is most common.
        merged.sort(key=lambda task: task.start_time, reverse=True)

        return merged
    except Exception as e:
        raise HTTPException(
            HTTPStatus.INTERNAL_SERVER_ERROR, f"Failed to get all tasks: {e}"
        )


@router.post("/admin/query-history/start-export")
def start_query_history_export(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, str]:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

    start = start or datetime.fromtimestamp(0, tz=timezone.utc)
    end = end or datetime.now(tz=timezone.utc)

    if start >= end:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            f"Start time must come before end time, but instead got the start time coming after; {start=} {end=}",
        )

    task_id_uuid = uuid.uuid4()
    task_id = str(task_id_uuid)
    start_time = datetime.now(tz=timezone.utc)

    register_task(
        db_session=db_session,
        task_name=query_history_task_name(start=start, end=end),
        task_id=task_id,
        status=TaskStatus.PENDING,
        start_time=start_time,
    )

    client_app.send_task(
        OnyxCeleryTask.EXPORT_QUERY_HISTORY_TASK,
        task_id=task_id,
        priority=OnyxCeleryPriority.MEDIUM,
        queue=OnyxCeleryQueues.CSV_GENERATION,
        kwargs={
            "start": start,
            "end": end,
            "start_time": start_time,
            "tenant_id": get_current_tenant_id(),
        },
    )

    return {"request_id": task_id}


@router.get("/admin/query-history/export-status")
def get_query_history_export_status(
    request_id: str,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

    task = get_task_with_id(db_session=db_session, task_id=request_id)

    if task:
        return {"status": task.status}

    # If task is None, then it's possible that the task has already finished processing.
    # Therefore, we should then check if the export file has already been stored inside of the file-store.
    # If that *also* doesn't exist, then we can return a 404.
    file_store = get_default_file_store()

    report_name = construct_query_history_report_name(request_id)
    has_file = file_store.has_file(
        file_id=report_name,
        file_origin=FileOrigin.QUERY_HISTORY_CSV,
        file_type=FileType.CSV,
    )

    if not has_file:
        raise HTTPException(
            HTTPStatus.NOT_FOUND,
            f"No task with {request_id=} was found",
        )

    return {"status": TaskStatus.SUCCESS}


@router.get("/admin/query-history/download")
def download_query_history_csv(
    request_id: str,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

    report_name = construct_query_history_report_name(request_id)
    file_store = get_default_file_store()
    has_file = file_store.has_file(
        file_id=report_name,
        file_origin=FileOrigin.QUERY_HISTORY_CSV,
        file_type=FileType.CSV,
    )

    if has_file:
        try:
            csv_stream = file_store.read_file(report_name)
        except Exception as e:
            raise HTTPException(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"Failed to read query history file: {str(e)}",
            )
        csv_stream.seek(0)
        return StreamingResponse(
            iter(csv_stream),
            media_type=FileType.CSV,
            headers={"Content-Disposition": f"attachment;filename={report_name}"},
        )

    # If the file doesn't exist yet, it may still be processing.
    # Therefore, we check the task queue to determine its status, if there is any.
    task = get_task_with_id(db_session=db_session, task_id=request_id)
    if not task:
        raise HTTPException(
            HTTPStatus.NOT_FOUND,
            f"No task with {request_id=} was found",
        )

    if task.status in [TaskStatus.STARTED, TaskStatus.PENDING]:
        raise HTTPException(
            HTTPStatus.ACCEPTED, f"Task with {request_id=} is still being worked on"
        )

    elif task.status == TaskStatus.FAILURE:
        raise HTTPException(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            f"Task with {request_id=} failed to be processed",
        )
    else:
        # This is the final case in which `task.status == SUCCESS`
        raise RuntimeError(
            "The task was marked as success, the file was not found in the file store; this is an internal error..."
        )
