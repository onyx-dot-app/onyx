from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from ee.onyx.background.task_name_builders import QUERY_HISTORY_TASK_NAME_PREFIX
from onyx.auth.users import get_display_email
from onyx.background.task_utils import extract_task_id_from_query_history_report_name
from onyx.configs.constants import MessageType
from onyx.configs.constants import QAFeedbackType
from onyx.configs.constants import SessionType
from onyx.db.enums import TaskStatus
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import FileRecord
from onyx.db.models import TaskQueueState


class AbridgedSearchDoc(BaseModel):
    """A subset of the info present in `SearchDoc`"""

    document_id: str
    semantic_identifier: str
    link: str | None


class MessageSnapshot(BaseModel):
    id: int
    message: str
    message_type: MessageType
    documents: list[AbridgedSearchDoc]
    feedback_type: QAFeedbackType | None
    feedback_text: str | None
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
            id=message.id,
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
    id: UUID
    user_email: str
    name: str | None
    first_user_message: str
    first_ai_message: str
    assistant_id: int | None
    assistant_name: str | None
    time_created: datetime
    feedback_type: QAFeedbackType | None
    flow_type: SessionType
    conversation_length: int

    @classmethod
    def from_chat_session(cls, chat_session: ChatSession) -> "ChatSessionMinimal":
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

        list_of_message_feedbacks = [
            feedback.is_positive
            for message in chat_session.messages
            for feedback in message.chat_message_feedbacks
        ]
        session_feedback_type = None
        if list_of_message_feedbacks:
            if all(list_of_message_feedbacks):
                session_feedback_type = QAFeedbackType.LIKE
            elif not any(list_of_message_feedbacks):
                session_feedback_type = QAFeedbackType.DISLIKE
            else:
                session_feedback_type = QAFeedbackType.MIXED

        return cls(
            id=chat_session.id,
            user_email=get_display_email(
                chat_session.user.email if chat_session.user else None
            ),
            name=chat_session.description,
            first_user_message=first_user_message,
            first_ai_message=first_ai_message,
            assistant_id=chat_session.persona_id,
            assistant_name=(
                chat_session.persona.name if chat_session.persona else None
            ),
            time_created=chat_session.time_created,
            feedback_type=session_feedback_type,
            flow_type=(
                SessionType.SLACK if chat_session.onyxbot_flow else SessionType.CHAT
            ),
            conversation_length=len(
                [
                    message
                    for message in chat_session.messages
                    if message.message_type != MessageType.SYSTEM
                ]
            ),
        )


class ChatSessionSnapshot(BaseModel):
    id: UUID
    user_email: str
    name: str | None
    messages: list[MessageSnapshot]
    assistant_id: int | None
    assistant_name: str | None
    time_created: datetime
    flow_type: SessionType


class QuestionAnswerPairSnapshot(BaseModel):
    chat_session_id: UUID
    # 1-indexed message number in the chat_session
    # e.g. the first message pair in the chat_session is 1, the second is 2, etc.
    message_pair_num: int
    user_message: str
    ai_response: str
    retrieved_documents: list[AbridgedSearchDoc]
    feedback_type: QAFeedbackType | None
    feedback_text: str | None
    persona_name: str | None
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
                persona_name=chat_session_snapshot.assistant_name,
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
            "persona_name": self.persona_name,
            "user_email": self.user_email,
            "time_created": str(self.time_created),
            "flow_type": self.flow_type,
        }


class QueryHistoryExport(BaseModel):
    task_id: str
    status: TaskStatus
    start: datetime
    end: datetime
    start_time: datetime

    @classmethod
    def from_task(
        cls,
        task_queue_state: TaskQueueState,
    ) -> "QueryHistoryExport":
        start_end = task_queue_state.task_name.removeprefix(
            f"{QUERY_HISTORY_TASK_NAME_PREFIX}_"
        )
        start, end = start_end.split("_")

        if not task_queue_state.start_time:
            raise RuntimeError("The start time of the task must always be present")

        return cls(
            task_id=task_queue_state.task_id,
            status=task_queue_state.status,
            start=datetime.fromisoformat(start),
            end=datetime.fromisoformat(end),
            start_time=task_queue_state.start_time,
        )

    @classmethod
    def from_file(
        cls,
        file: FileRecord,
    ) -> "QueryHistoryExport":
        if not file.file_metadata or not isinstance(file.file_metadata, dict):
            raise RuntimeError(
                "The file metadata must be non-null, and must be of type `dict[str, str]`"
            )

        metadata = QueryHistoryFileMetadata.model_validate(dict(file.file_metadata))
        task_id = extract_task_id_from_query_history_report_name(file.file_id)

        return cls(
            task_id=task_id,
            status=TaskStatus.SUCCESS,
            start=metadata.start,
            end=metadata.end,
            start_time=metadata.start_time,
        )


class QueryHistoryFileMetadata(BaseModel):
    start: datetime
    end: datetime
    start_time: datetime
