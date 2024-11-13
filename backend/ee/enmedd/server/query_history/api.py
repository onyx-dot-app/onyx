import csv
import io
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import List
from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.enmedd.db.query_history import fetch_chat_sessions_eagerly_by_time
from enmedd.auth.users import current_teamspace_admin_user
from enmedd.auth.users import current_workspace_admin_user
from enmedd.auth.users import get_display_email
from enmedd.chat.chat_utils import create_chat_chain
from enmedd.configs.constants import MessageType
from enmedd.configs.constants import QAFeedbackType
from enmedd.configs.constants import SessionType
from enmedd.db.chat import get_chat_session_by_id
from enmedd.db.engine import get_session
from enmedd.db.models import ChatMessage
from enmedd.db.models import ChatSession
from enmedd.db.models import User
from enmedd.server.models import MinimalTeamspaceSnapshot

router = APIRouter()


class AbridgedSearchDoc(BaseModel):
    """A subset of the info present in `SearchDoc`"""

    document_id: str
    semantic_identifier: str
    link: Optional[str] = None


class MessageSnapshot(BaseModel):
    message: str
    message_type: MessageType
    documents: list[AbridgedSearchDoc]
    feedback_type: QAFeedbackType | None
    feedback_text: Optional[str] = None
    time_created: datetime

    @classmethod
    def build(cls, message: ChatMessage) -> "MessageSnapshot":
        latest_messages_feedback_obj = (
            message.chat_message_feedbacks[-1]
            if len(message.chat_message_feedbacks) > 0
            else None
        )
        feedback_type = (
            (
                QAFeedbackType.LIKE
                if latest_messages_feedback_obj.is_positive
                else QAFeedbackType.DISLIKE
            )
            if latest_messages_feedback_obj
            else None
        )
        feedback_text = (
            latest_messages_feedback_obj.feedback_text
            if latest_messages_feedback_obj
            else None
        )
        return cls(
            message=message.message,
            message_type=message.message_type,
            documents=[
                AbridgedSearchDoc(
                    document_id=document.document_id,
                    semantic_identifier=document.semantic_id,
                    link=document.link,
                )
                for document in message.search_docs
            ],
            feedback_type=feedback_type,
            feedback_text=feedback_text,
            time_created=message.time_sent,
        )


class ChatSessionMinimal(BaseModel):
    id: int
    user_email: str
    name: Optional[str] = None
    first_user_message: str
    first_ai_message: str
    assistant_name: str
    time_created: datetime
    feedback_type: QAFeedbackType | Literal["mixed"] | None
    groups: Optional[List[MinimalTeamspaceSnapshot]] = None


class ChatSessionSnapshot(BaseModel):
    id: int
    user_email: str
    name: Optional[str] = None
    messages: list[MessageSnapshot]
    assistant_name: str
    time_created: datetime
    groups: Optional[List[MinimalTeamspaceSnapshot]] = None
    flow_type: SessionType


class QuestionAnswerPairSnapshot(BaseModel):
    chat_session_id: int
    # 1-indexed message number in the chat_session
    # e.g. the first message pair in the chat_session is 1, the second is 2, etc.
    message_pair_num: int
    user_message: str
    ai_response: str
    retrieved_documents: list[AbridgedSearchDoc]
    feedback_type: QAFeedbackType | None
    feedback_text: Optional[str] = None
    assistant_name: str
    user_email: str
    time_created: datetime
    flow_type: SessionType

    @classmethod
    def from_chat_session_snapshot(
        cls,
        chat_session_snapshot: ChatSessionSnapshot,
    ) -> list["QuestionAnswerPairSnapshot"]:
        message_pairs: list[tuple[MessageSnapshot, MessageSnapshot]] = []
        for ind in range(1, len(chat_session_snapshot.messages), 2):
            message_pairs.append(
                (
                    chat_session_snapshot.messages[ind - 1],
                    chat_session_snapshot.messages[ind],
                )
            )

        return [
            cls(
                chat_session_id=chat_session_snapshot.id,
                message_pair_num=ind + 1,
                user_message=user_message.message,
                ai_response=ai_message.message,
                retrieved_documents=ai_message.documents,
                feedback_type=ai_message.feedback_type,
                feedback_text=ai_message.feedback_text,
                assistant_name=chat_session_snapshot.assistant_name,
                user_email=get_display_email(chat_session_snapshot.user_email),
                time_created=user_message.time_created,
                flow_type=chat_session_snapshot.flow_type,
            )
            for ind, (user_message, ai_message) in enumerate(message_pairs)
        ]

    def to_json(self) -> dict[str, str | None]:
        return {
            "chat_session_id": str(self.chat_session_id),
            "message_pair_num": str(self.message_pair_num),
            "user_message": self.user_message,
            "ai_response": self.ai_response,
            "retrieved_documents": "|".join(
                [
                    doc.link or doc.semantic_identifier
                    for doc in self.retrieved_documents
                ]
            ),
            "feedback_type": self.feedback_type.value if self.feedback_type else "",
            "feedback_text": self.feedback_text or "",
            "assistant_name": self.assistant_name,
            "user_email": self.user_email,
            "time_created": str(self.time_created),
            "flow_type": self.flow_type,
        }


def determine_flow_type(chat_session: ChatSession) -> SessionType:
    return SessionType.SEARCH if chat_session.one_shot else SessionType.CHAT


def fetch_and_process_chat_session_history_minimal(
    db_session: Session,
    start: datetime,
    end: datetime,
    feedback_filter: QAFeedbackType | None = None,
    teamspace_id: Optional[int] = None,
    limit: int | None = 500,
) -> list[ChatSessionMinimal]:
    chat_sessions = fetch_chat_sessions_eagerly_by_time(
        start=start,
        end=end,
        db_session=db_session,
        limit=limit,
        teamspace_id=teamspace_id,
    )

    minimal_sessions = []
    for chat_session in chat_sessions:
        if not chat_session.messages:
            continue

        first_user_message = next(
            (
                message.message
                for message in chat_session.messages
                if message.message_type == MessageType.USER
            ),
            "",
        )
        first_ai_message = next(
            (
                message.message
                for message in chat_session.messages
                if message.message_type == MessageType.ASSISTANT
            ),
            "",
        )

        has_positive_feedback = any(
            feedback.is_positive
            for message in chat_session.messages
            for feedback in message.chat_message_feedbacks
        )

        has_negative_feedback = any(
            not feedback.is_positive
            for message in chat_session.messages
            for feedback in message.chat_message_feedbacks
        )

        feedback_type: QAFeedbackType | Literal["mixed"] | None = (
            "mixed"
            if has_positive_feedback and has_negative_feedback
            else QAFeedbackType.LIKE
            if has_positive_feedback
            else QAFeedbackType.DISLIKE
            if has_negative_feedback
            else None
        )

        if feedback_filter:
            if feedback_filter == QAFeedbackType.LIKE and not has_positive_feedback:
                continue
            if feedback_filter == QAFeedbackType.DISLIKE and not has_negative_feedback:
                continue

        flow_type = determine_flow_type(chat_session)

        minimal_sessions.append(
            ChatSessionMinimal(
                id=chat_session.id,
                user_email=get_display_email(
                    chat_session.user.email if chat_session.user else None
                ),
                name=chat_session.description,
                first_user_message=first_user_message,
                first_ai_message=first_ai_message,
                assistant_name=chat_session.assistant.name
                if chat_session.assistant
                else None,
                time_created=chat_session.time_created,
                feedback_type=feedback_type,
                flow_type=flow_type,
            )
        )

    return minimal_sessions


def fetch_and_process_chat_session_history(
    db_session: Session,
    start: datetime,
    end: datetime,
    feedback_type: QAFeedbackType | None,
    limit: int | None = 500,
    teamspace_id: Optional[int] = None,
) -> list[ChatSessionSnapshot]:
    chat_sessions = fetch_chat_sessions_eagerly_by_time(
        start=start,
        end=end,
        db_session=db_session,
        limit=limit,
        teamspace_id=teamspace_id,
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

    flow_type = determine_flow_type(chat_session)

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
        assistant_name=chat_session.assistant.name if chat_session.assistant else None,
        time_created=chat_session.time_created,
        flow_type=flow_type,
    )


@router.get("/admin/chat-session-history")
def get_chat_session_history(
    feedback_type: QAFeedbackType | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    _: User | None = Depends(current_teamspace_admin_user),
    db_session: Session = Depends(get_session),
    teamspace_id: Optional[int] = None,
) -> list[ChatSessionMinimal]:
    return fetch_and_process_chat_session_history_minimal(
        db_session=db_session,
        start=start
        or (
            datetime.now(tz=timezone.utc) - timedelta(days=30)
        ),  # default is 30d lookback
        end=end or datetime.now(tz=timezone.utc),
        feedback_filter=feedback_type,
        teamspace_id=teamspace_id,
    )


@router.get("/admin/chat-session-history/{chat_session_id}")
def get_chat_session_admin(
    chat_session_id: int,
    _: User | None = Depends(current_workspace_admin_user),
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
    _: User | None = Depends(current_teamspace_admin_user),
    db_session: Session = Depends(get_session),
    teamspace_id: Optional[int] = None,
) -> StreamingResponse:
    complete_chat_session_history = fetch_and_process_chat_session_history(
        db_session=db_session,
        start=datetime.fromtimestamp(0, tz=timezone.utc),
        end=datetime.now(tz=timezone.utc),
        feedback_type=None,
        limit=None,
        teamspace_id=teamspace_id,
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
        headers={
            "Content-Disposition": "attachment;filename=VanguardAI_query_history.csv"
        },
    )
