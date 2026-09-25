from collections.abc import Iterator
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStreamPart, StreamingError
from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.chat import create_chat_session_from_request
from onyx.db.models import ChatSession, User
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    Packet,
)


def final_answer(parts: list[AnswerStreamPart]) -> str:
    errors = [part for part in parts if isinstance(part, StreamingError)]
    assert not errors, errors
    answer = ""
    for part in parts:
        if not isinstance(part, Packet) or part.placement.sub_turn_index is not None:
            continue
        if isinstance(part.obj, AgentResponseStart):
            answer = ""
        elif isinstance(part.obj, AgentResponseDelta):
            answer += part.obj.content
    assert answer, "Expected assistant answer content"
    return answer


def submit_query(
    query: str,
    chat_session_id: UUID | None,
    user: User,
    llm_override: LLMOverride | None = None,
) -> Iterator[AnswerStreamPart]:
    request = SendMessageRequest(
        message=query,
        chat_session_id=chat_session_id,
        stream=True,
        chat_session_info=(
            ChatSessionCreationRequest() if chat_session_id is None else None
        ),
        llm_override=llm_override,
    )

    return handle_stream_message_objects(
        new_msg_req=request,
        user=user,
    )


def create_chat_session(
    db_session: Session,
    user: User,
) -> ChatSession:
    return create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(),
        user=user,
        db_session=db_session,
    )
