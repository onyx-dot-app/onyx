import io
from datetime import datetime
from datetime import timezone
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ee.onyx.background.celery.apps.primary import query_history_report_task
from ee.onyx.db.query_history import get_page_of_chat_sessions
from ee.onyx.db.query_history import get_total_filtered_chat_sessions_count
from ee.onyx.server.query_history.models import ChatSessionMinimal
from ee.onyx.server.query_history.models import ChatSessionSnapshot
from ee.onyx.server.query_history.utils import ONYX_ANONYMIZED_EMAIL
from ee.onyx.server.query_history.utils import snapshot_from_chat_session
from onyx.auth.users import current_admin_user
from onyx.configs.app_configs import ONYX_QUERY_HISTORY_TYPE
from onyx.configs.constants import QAFeedbackType
from onyx.configs.constants import QueryHistoryType
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_chat_sessions_by_user
from onyx.db.engine import get_session
from onyx.db.enums import TaskStatus
from onyx.db.models import User
from onyx.db.tasks import get_task_by_task_id
from onyx.server.documents.models import PaginatedReturn
from onyx.server.query_and_chat.models import ChatSessionDetails
from onyx.server.query_and_chat.models import ChatSessionsResponse

router = APIRouter()


@router.get("/admin/chat-sessions")
def get_user_chat_sessions(
    user_id: UUID,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionsResponse:
    # we specifically don't allow this endpoint if "anonymized" since
    # this is a direct query on the user id
    if ONYX_QUERY_HISTORY_TYPE in [
        QueryHistoryType.DISABLED,
        QueryHistoryType.ANONYMIZED,
    ]:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Per user query history has been disabled by the administrator.",
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
                folder_id=chat.folder_id,
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
    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.DISABLED:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )

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
    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.DISABLED:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )

    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_session_id,
            user_id=None,  # view chat regardless of user
            db_session=db_session,
            include_deleted=True,
        )
    except ValueError:
        raise HTTPException(
            400, f"Chat session with id '{chat_session_id}' does not exist."
        )
    snapshot = snapshot_from_chat_session(
        chat_session=chat_session, db_session=db_session
    )

    if snapshot is None:
        raise HTTPException(
            400,
            f"Could not create snapshot for chat session with id '{chat_session_id}'",
        )

    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
        snapshot.user_email = ONYX_ANONYMIZED_EMAIL

    return snapshot


@router.post("/admin/query-history-csv")
def post_query_history_as_csv(
    response: Response,
    start: datetime | None = None,
    end: datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.DISABLED:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )

    start = start or datetime.fromtimestamp(0, tz=timezone.utc)
    end = end or datetime.now(tz=timezone.utc)
    task = query_history_report_task.delay(
        start=start,
        end=end,
    )

    response.status_code = HTTPStatus.ACCEPTED
    response.headers[
        "Location"
    ] = f"/admin/query-history-csv/status?request_id={task.id}"
    return {"request_id": task.id}


@router.get("/admin/query-history-csv/status")
def get_query_history_csv_status(
    request_id: str,
    response: Response,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, TaskStatus]:
    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.DISABLED:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )

    task_queue_state = get_task_by_task_id(request_id, db_session)
    if task_queue_state is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Task queue state not found for task id.",
        )

    return {
        "status": task_queue_state.status,
    }


@router.get("/admin/query-history-csv/download")
def download_query_history_csv(
    request_id: str,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.DISABLED:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )

    task_queue_state = get_task_by_task_id(request_id, db_session)
    if task_queue_state is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Task queue state not found for task id.",
        )
    elif task_queue_state.status == TaskStatus.FAILURE:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Task failed to complete.",
        )
    elif task_queue_state.status != TaskStatus.SUCCESS:
        raise HTTPException(
            status_code=HTTPStatus.NO_CONTENT,
            detail="Task is still pending.",
        )

    # TODO: change this to read from the file store with the file name
    #       `query_history_report_{request_id}.csv`
    test_csv = "user_message,assistant_message,date\n"
    test_csv += "Hello, how are you?,I am fine,2021-01-01\n"
    test_csv += (
        "What is the weather in Tokyo?,The weather in Tokyo is sunny,2021-01-02\n"
    )
    test_csv += (
        "What is the capital of France?,The capital of France is Paris,2021-01-03\n"
    )
    return StreamingResponse(
        io.StringIO(test_csv),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment;filename=query_history.csv"},
    )
