from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.chat.chat_utils import create_chat_session_from_request
from onyx.chat.models import AnswerStreamPart
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.db.models import ChatSession
from onyx.db.models import User
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from tests.external_dependency_unit.mock_content_provider import MockWebContent
from tests.external_dependency_unit.mock_search_provider import MockWebSearchResult


def create_placement(
    turn_index: int,
    tab_index: int = 0,
    sub_turn_index: int | None = None,
) -> Placement:
    return Placement(
        turn_index=turn_index,
        tab_index=tab_index,
        sub_turn_index=sub_turn_index,
    )


def submit_query(
    query: str, chat_session_id: UUID | None, db_session: Session, user: User
) -> Iterator[AnswerStreamPart]:
    request = SendMessageRequest(
        message=query,
        chat_session_id=chat_session_id,
        stream=True,
        chat_session_info=(
            ChatSessionCreationRequest() if chat_session_id is None else None
        ),
    )

    return handle_stream_message_objects(
        new_msg_req=request,
        user=user,
        db_session=db_session,
    )


def create_chat_session(
    db_session: Session,
    user: User,
) -> ChatSession:
    return create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(),
        user_id=user.id,
        db_session=db_session,
    )


def create_packet_with_agent_response_delta(token: str, turn_index: int) -> Packet:
    return Packet(
        placement=create_placement(turn_index),
        obj=AgentResponseDelta(
            content=token,
        ),
    )


def create_packet_with_reasoning_delta(token: str, turn_index: int) -> Packet:
    return Packet(
        placement=create_placement(turn_index),
        obj=ReasoningDelta(
            reasoning=token,
        ),
    )


def create_web_search_doc(
    semantic_identifier: str,
    link: str,
    blurb: str,
) -> SearchDoc:
    return SearchDoc(
        document_id=f"WEB_SEARCH_DOC_{link}",
        chunk_ind=0,
        semantic_identifier=semantic_identifier,
        link=link,
        blurb=blurb,
        source_type=DocumentSource.WEB,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
    )


def mock_web_search_result_to_search_doc(result: MockWebSearchResult) -> SearchDoc:
    return create_web_search_doc(
        semantic_identifier=result.title,
        link=result.link,
        blurb=result.snippet,
    )


def mock_web_content_to_search_doc(content: MockWebContent) -> SearchDoc:
    return create_web_search_doc(
        semantic_identifier=content.title,
        link=content.url,
        blurb=content.title,
    )


def tokenise(text: str) -> list[str]:
    return [(token + " ") for token in text.split(" ")]
