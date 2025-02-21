import csv
import io
from datetime import datetime
from datetime import timezone
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ee.onyx.db.query_history import fetch_chat_sessions_eagerly_by_time
from ee.onyx.db.query_history import get_page_of_chat_sessions
from ee.onyx.db.query_history import get_total_filtered_chat_sessions_count
from ee.onyx.server.query_history.models import ChatSessionMinimal
from ee.onyx.server.query_history.models import ChatSessionSnapshot
from ee.onyx.server.query_history.models import MessageSnapshot
from ee.onyx.server.query_history.models import QuestionAnswerPairSnapshot
from onyx.auth.users import current_admin_user
from onyx.auth.users import get_display_email
from onyx.chat.chat_utils import create_chat_chain
from onyx.configs.constants import MessageType
from onyx.configs.constants import QAFeedbackType
from onyx.configs.constants import SessionType
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_chat_sessions_by_user
from onyx.db.engine import get_session
from onyx.db.models import ChatSession
from onyx.db.models import User
from onyx.server.documents.models import PaginatedReturn
from onyx.server.query_and_chat.models import ChatSessionDetails
from onyx.server.query_and_chat.models import ChatSessionsResponse

router = APIRouter()


def fetch_and_process_chat_session_history(
    db_session: Session,
    start: datetime,
    end: datetime,
    feedback_type: QAFeedbackType | None,
    limit: int | None = 500,
) -> list[ChatSessionSnapshot]:
    chat_sessions = fetch_chat_sessions_eagerly_by_time(
        start=start, end=end, db_session=db_session, limit=limit
    )

    chat_session_snapshots = [
        snapshot_from_chat_session(chat_session=chat_session, db_session=db_session)
        for chat_session in chat_sessions
    ]

    valid_snapshots = [
        snapshot for snapshot in chat_session_snapshots if snapshot is not None
    ]

    if feedback_type:
        valid_snapshots = [
            snapshot
            for snapshot in valid_snapshots
            if any(
                message.feedback_type == feedback_type for message in snapshot.messages
            )
        ]

    return valid_snapshots


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
def get_user_chat_sessions(
    user_id: UUID,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionsResponse:
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

    return PaginatedReturn(
        items=[
            ChatSessionMinimal.from_chat_session(chat_session)
            for chat_session in page_of_chat_sessions
        ],
        total_items=total_filtered_chat_sessions_count,
    )


@router.get("/admin/chat-session-history/{chat_session_id}")
def get_chat_session_admin(
    chat_session_id: UUID,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionSnapshot:
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

    return snapshot


@router.get("/admin/query-history-csv")
def get_query_history_as_csv(
    _: User | None = Depends(current_admin_user),
    start: datetime | None = None,
    end: datetime | None = None,
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    complete_chat_session_history = fetch_and_process_chat_session_history(
        db_session=db_session,
        start=start or datetime.fromtimestamp(0, tz=timezone.utc),
        end=end or datetime.now(tz=timezone.utc),
        feedback_type=None,
        limit=None,
    )

    question_answer_pairs: list[QuestionAnswerPairSnapshot] = []
    for chat_session_snapshot in complete_chat_session_history:
        question_answer_pairs.extend(
            QuestionAnswerPairSnapshot.from_chat_session_snapshot(chat_session_snapshot)
        )

    # Create an in-memory text stream
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream, fieldnames=list(QuestionAnswerPairSnapshot.model_fields.keys())
    )
    writer.writeheader()
    for row in question_answer_pairs:
        writer.writerow(row.to_json())

    # Reset the stream's position to the start
    stream.seek(0)

    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment;filename=onyx_query_history.csv"},
    )
