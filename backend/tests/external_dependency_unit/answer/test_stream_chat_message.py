from __future__ import annotations

from collections.abc import Iterator
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.chat.chat_utils import create_chat_session_from_request
from onyx.chat.models import AnswerStreamPart
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.models import ChatSession
from onyx.db.models import User
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.mock_llm import use_mock_llm

DEFAULT_PLACEMENT = Placement(
    turn_index=0,
    tab_index=0,
    sub_turn_index=None,
)


def submit_query(
    query: str, chat_session_id: UUID | None, db_session: Session, user: User
) -> Iterator[AnswerStreamPart]:
    request = SendMessageRequest(
        message=query,
        chat_session_id=chat_session_id,
        stream=True,
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


def create_packet_with_agent_response_delta(token: str) -> Packet:
    return Packet(
        placement=DEFAULT_PLACEMENT,
        obj=AgentResponseDelta(
            content=token,
        ),
    )


def assert_answer_stream_part_correct(
    received: AnswerStreamPart, expected: AnswerStreamPart
) -> None:
    assert isinstance(received, type(expected))

    if isinstance(received, Packet):
        r_packet = cast(Packet, received)
        e_packet = cast(Packet, expected)

        assert r_packet.placement == e_packet.placement
        assert r_packet.obj == e_packet.obj
    elif isinstance(received, MessageResponseIDInfo):
        # We're not going to make assumptions about what the user id / assistant id should be
        # So just return
        return
    else:
        raise NotImplementedError("Not implemented")


def test_stream_chat_with_answer(
    db_session: Session,
    full_deployment_setup: None,
    mock_external_deps: None,
) -> None:
    """Test that the stream chat with answer endpoint returns a valid answer."""
    ensure_default_llm_provider(db_session)
    test_user = create_test_user(
        db_session, email_prefix="test_stream_chat_with_answer"
    )

    query = "What is the capital of France?"
    answer = "The capital of France is Paris."

    answer_tokens = [(token + " ") for token in answer.split(" ")]

    with use_mock_llm() as mock_llm:
        mock_llm.set_response(answer_tokens)
        chat_session = create_chat_session(db_session=db_session, user=test_user)

        answer_stream = submit_query(
            query=query,
            chat_session_id=chat_session.id,
            db_session=db_session,
            user=test_user,
        )

        packet1 = next(answer_stream)
        expected_packet1 = MessageResponseIDInfo(
            user_message_id=1,
            reserved_assistant_message_id=1,
        )
        assert_answer_stream_part_correct(packet1, expected_packet1)

        # Stream first token
        mock_llm.forward(1)
        packet2 = next(answer_stream)
        expected_packet2 = Packet(
            placement=DEFAULT_PLACEMENT,
            obj=AgentResponseStart(),
        )

        assert_answer_stream_part_correct(packet2, expected_packet2)

        for word in answer.split(" "):
            expected_token = word + " "
            expected_packet = create_packet_with_agent_response_delta(expected_token)

            packet = next(answer_stream)
            assert_answer_stream_part_correct(packet, expected_packet)
            mock_llm.forward(1)

        final_packet = next(answer_stream)
        expected_final_packet = Packet(
            placement=DEFAULT_PLACEMENT,
            obj=OverallStop(),
        )

        assert_answer_stream_part_correct(final_packet, expected_final_packet)

        with pytest.raises(StopIteration):
            next(answer_stream)
