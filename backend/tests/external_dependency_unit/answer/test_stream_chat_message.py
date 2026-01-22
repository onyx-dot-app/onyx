from __future__ import annotations

import json
from collections.abc import Iterator
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.chat.chat_utils import create_chat_session_from_request
from onyx.chat.models import AnswerStreamPart
from onyx.chat.models import CreateChatSessionID
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.db.models import User
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import OpenUrlDocuments
from onyx.server.query_and_chat.streaming_models import OpenUrlStart
from onyx.server.query_and_chat.streaming_models import OpenUrlUrls
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningDone
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.mock_content_provider import MockWebContent
from tests.external_dependency_unit.mock_content_provider import (
    use_mock_content_provider,
)
from tests.external_dependency_unit.mock_llm import LLMAnswerResponse
from tests.external_dependency_unit.mock_llm import LLMReasoningResponse
from tests.external_dependency_unit.mock_llm import LLMToolCallResponse
from tests.external_dependency_unit.mock_llm import use_mock_llm
from tests.external_dependency_unit.mock_search_provider import MockWebSearchResult
from tests.external_dependency_unit.mock_search_provider import use_mock_web_provider


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
) -> CreateChatSessionID:
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


def assert_answer_stream_part_correct(
    received: AnswerStreamPart, expected: AnswerStreamPart
) -> None:
    assert isinstance(received, type(expected))

    if isinstance(received, Packet):
        r_packet = cast(Packet, received)
        e_packet = cast(Packet, expected)

        assert r_packet.placement == e_packet.placement

        if isinstance(r_packet.obj, SearchToolDocumentsDelta):
            assert is_search_tool_document_delta_equal(r_packet.obj, e_packet.obj)
            return
        elif isinstance(r_packet.obj, OpenUrlDocuments):
            assert is_open_url_documents_equal(r_packet.obj, e_packet.obj)
            return
        elif isinstance(r_packet.obj, AgentResponseStart):
            assert is_agent_response_start_equal(r_packet.obj, e_packet.obj)
            return

        assert r_packet.obj == e_packet.obj
    elif isinstance(received, MessageResponseIDInfo):
        # We're not going to make assumptions about what the user id / assistant id should be
        # So just return
        return
    elif isinstance(received, CreateChatSessionID):
        # Don't worry about same session ids
        return
    else:
        raise NotImplementedError("Not implemented")


def _are_search_docs_equal(
    received: list[SearchDoc],
    expected: list[SearchDoc],
) -> bool:
    """
    What we care about:
     - All documents are present (order does not)
     - Expected document_id, link, blurb, source_type and hidden
    """
    if len(received) != len(expected):
        return False

    received.sort(key=lambda x: x.document_id)
    expected.sort(key=lambda x: x.document_id)

    for received_document, expected_document in zip(received, expected):
        if received_document.document_id != expected_document.document_id:
            return False
        if received_document.link != expected_document.link:
            return False
        if received_document.blurb != expected_document.blurb:
            return False
        if received_document.source_type != expected_document.source_type:
            return False
        if received_document.hidden != expected_document.hidden:
            return False
    return True


def is_search_tool_document_delta_equal(
    received: SearchToolDocumentsDelta,
    expected: SearchToolDocumentsDelta,
) -> bool:
    """
    What we care about:
     - All documents are present (order does not)
     - Expected document_id, link, blurb, source_type and hidden
    """
    received_documents = received.documents
    expected_documents = expected.documents

    return _are_search_docs_equal(received_documents, expected_documents)


def is_open_url_documents_equal(
    received: OpenUrlDocuments,
    expected: OpenUrlDocuments,
) -> bool:
    """
    What we care about:
     - All documents are present (order does not)
     - Expected document_id, link, blurb, source_type and hidden
    """
    received_documents = received.documents
    expected_documents = expected.documents

    return _are_search_docs_equal(received_documents, expected_documents)


def is_agent_response_start_equal(
    received: AgentResponseStart,
    expected: AgentResponseStart,
) -> bool:
    """
    What we care about:
     - All documents are present (order does not)
     - Expected document_id, link, blurb, source_type and hidden
    """
    received_documents = received.final_documents
    expected_documents = expected.final_documents

    if received_documents is None and expected_documents is None:
        return True
    if not received_documents or not expected_documents:
        return False

    return _are_search_docs_equal(received_documents, expected_documents)


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
        mock_llm.add_response(LLMAnswerResponse(answer_tokens=answer_tokens))
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
            placement=create_placement(0),
            obj=AgentResponseStart(),
        )

        assert_answer_stream_part_correct(packet2, expected_packet2)

        for word in answer.split(" "):
            expected_token = word + " "
            expected_packet = create_packet_with_agent_response_delta(expected_token, 0)

            packet = next(answer_stream)
            assert_answer_stream_part_correct(packet, expected_packet)
            mock_llm.forward(1)

        final_packet = next(answer_stream)
        expected_final_packet = Packet(
            placement=create_placement(0),
            obj=OverallStop(),
        )

        assert_answer_stream_part_correct(final_packet, expected_final_packet)

        with pytest.raises(StopIteration):
            next(answer_stream)


def test_stream_chat_with_answer_create_chat(
    db_session: Session,
    full_deployment_setup: None,
    mock_external_deps: None,
) -> None:
    ensure_default_llm_provider(db_session)
    test_user = create_test_user(
        db_session, email_prefix="test_stream_chat_with_answer_create_chat"
    )

    query = "Hi there friends"
    answer = "Hello friend"

    tokens = [answer]

    with use_mock_llm() as mock_llm:
        mock_llm.add_response(LLMAnswerResponse(answer_tokens=tokens))
        answer_stream = submit_query(
            query=query,
            chat_session_id=None,
            db_session=db_session,
            user=test_user,
        )

        p1 = next(answer_stream)
        ep1 = CreateChatSessionID(
            chat_session_id=UUID("123e4567-e89b-12d3-a456-426614174000")
        )
        assert_answer_stream_part_correct(p1, ep1)

        p2 = next(answer_stream)
        ep2 = MessageResponseIDInfo(
            user_message_id=1,
            reserved_assistant_message_id=2,
        )
        assert_answer_stream_part_correct(p2, ep2)

        # Stream the token
        mock_llm.forward(1)

        p3 = next(answer_stream)
        ep3 = Packet(
            placement=create_placement(0),
            obj=AgentResponseStart(),
        )
        assert_answer_stream_part_correct(p3, ep3)

        p4 = next(answer_stream)
        ep4 = Packet(
            placement=create_placement(0),
            obj=AgentResponseDelta(
                content=answer,
            ),
        )
        assert_answer_stream_part_correct(p4, ep4)

        p5 = next(answer_stream)
        ep5 = Packet(
            placement=create_placement(0),
            obj=OverallStop(),
        )
        assert_answer_stream_part_correct(p5, ep5)

        with pytest.raises(StopIteration):
            next(answer_stream)


def test_stream_chat_with_search_and_openurl_tools(
    db_session: Session,
    full_deployment_setup: None,
    mock_external_deps: None,
) -> None:
    """
    Test flow:
    1. User queries for the weather in Sydney
    2. LLM thinks and decides to run a search
    3. Search is ran with some websites + content provided
    4. LLM decides which websites it will want to read from
    4. Tool reads those websites
    5. LLM summarizes the websites and returns the answer
    """
    ensure_default_llm_provider(db_session)
    test_user = create_test_user(
        db_session, email_prefix="test_stream_chat_with_search_tool"
    )

    query = "What is the weather in Sydney?"

    with (
        use_mock_llm() as mock_llm,
        use_mock_web_provider(db_session) as mock_web,
        use_mock_content_provider() as mock_content,
    ):
        llm_thinking_response = (
            "I need to perform a web search to get current weather details. "
            "I can use the search tool to do this."
        )
        mock_llm.add_response(
            LLMReasoningResponse(
                reasoning_tokens=[
                    (token + " ") for token in llm_thinking_response.split(" ")
                ]
            )
        )

        tool_call_query_dict = {
            "queries": ["weather in sydney", "current weather in sydney"]
        }
        tool_call_query_string = json.dumps(tool_call_query_dict)
        mock_llm.add_response(
            LLMToolCallResponse(
                tool_name="web_search",
                tool_call_id="123",
                tool_call_argument_tokens=[tool_call_query_string],
            )
        )

        chat_session = create_chat_session(db_session=db_session, user=test_user)

        answer_stream = submit_query(
            query=query,
            chat_session_id=chat_session.id,
            db_session=db_session,
            user=test_user,
        )

        # Part 0: Message is created
        p1 = next(answer_stream)
        ep1 = MessageResponseIDInfo(
            user_message_id=1,
            reserved_assistant_message_id=1,
        )
        assert_answer_stream_part_correct(p1, ep1)

        # Part 1: Start reasoning about what to do
        mock_llm.forward(len(llm_thinking_response.split(" ")) + 1)
        p2 = next(answer_stream)
        expected_packet2 = Packet(
            placement=create_placement(0),
            obj=ReasoningStart(),
        )
        assert_answer_stream_part_correct(p2, expected_packet2)

        for token in llm_thinking_response.split(" "):
            expected_token = token + " "
            expected_packet = create_packet_with_reasoning_delta(expected_token, 0)

            packet = next(answer_stream)
            assert_answer_stream_part_correct(packet, expected_packet)

        p3 = next(answer_stream)
        expected_packet3 = Packet(
            placement=create_placement(0),
            obj=ReasoningDone(),
        )
        assert_answer_stream_part_correct(p3, expected_packet3)

        # Part 2: Start the web search tool call
        mock_llm.forward(len(tool_call_query_string.split(" ")))

        p4 = next(answer_stream)
        expected_packet4 = Packet(
            placement=create_placement(1, 0),
            obj=SearchToolStart(
                is_internet_search=True,
            ),
        )
        assert_answer_stream_part_correct(p4, expected_packet4)

        QUERY1 = "weather in sydney"
        QUERY2 = "current weather in sydney"

        RESULTS1 = [
            MockWebSearchResult(
                title="Official Weather",
                link="www.weather.com.au",
                snippet="The current weather in Sydney is 20 degrees Celsius.",
            ),
            MockWebSearchResult(
                title="Weather CHannel",
                link="www.wc.com.au",
                snippet="Morning is 10 degree Celsius, afternoon is 25 degrees Celsius.",
            ),
        ]

        RESULTS2 = [
            MockWebSearchResult(
                title="Weather Now!",
                link="www.weathernow.com.au",
                snippet="The weather right now is sunny with a temperature of 22 degrees Celsius.",
            )
        ]

        mock_web.add_results(QUERY1, RESULTS1)
        mock_web.add_results(QUERY2, RESULTS2)

        p5 = next(answer_stream)
        expected_packet5 = Packet(
            placement=create_placement(1, 0),
            obj=SearchToolQueriesDelta(
                queries=["weather in sydney", "current weather in sydney"],
            ),
        )
        assert_answer_stream_part_correct(p5, expected_packet5)

        DOCS1 = [
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.weather.com.au",
                chunk_ind=0,
                semantic_identifier="The current weather in Sydney is 20 degrees Celsius.",
                link="www.weather.com.au",
                blurb="The current weather in Sydney is 20 degrees Celsius.",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.wc.com.au",
                chunk_ind=0,
                semantic_identifier="Morning is 10 degree Celsius, afternoon is 25 degrees Celsius.",
                link="www.wc.com.au",
                blurb="Morning is 10 degree Celsius, afternoon is 25 degrees Celsius.",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.weathernow.com.au",
                chunk_ind=0,
                semantic_identifier="The weather right now is sunny with a temperature of 22 degrees Celsius.",
                link="www.weathernow.com.au",
                blurb="The weather right now is sunny with a temperature of 22 degrees Celsius.",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
        ]

        p6 = next(answer_stream)
        expected_packet6 = Packet(
            placement=create_placement(1, 0),
            obj=SearchToolDocumentsDelta(
                documents=DOCS1,
            ),
        )

        assert_answer_stream_part_correct(p6, expected_packet6)

        p7 = next(answer_stream)
        expected_packet7 = Packet(placement=create_placement(1, 0), obj=SectionEnd())
        assert_answer_stream_part_correct(p7, expected_packet7)

        REASONING_TEXT = "I like weathernow and the official weather site"
        REASONING_TOKENS = [(token + " ") for token in REASONING_TEXT.split(" ")]
        mock_llm.add_response(
            LLMReasoningResponse(
                reasoning_tokens=REASONING_TOKENS,
            )
        )

        tool_call_query_dict = {"urls": ["www.weathernow.com.au", "www.weather.com.au"]}
        tool_call_query_string = json.dumps(tool_call_query_dict)
        mock_llm.add_response(
            LLMToolCallResponse(
                tool_name="open_url",
                tool_call_id="123",
                tool_call_argument_tokens=[tool_call_query_string],
            )
        )

        mock_llm.forward_till_end()

        p8 = next(answer_stream)
        expected_packet8 = Packet(
            placement=create_placement(2),
            obj=ReasoningStart(),
        )
        assert_answer_stream_part_correct(p8, expected_packet8)

        for token in REASONING_TEXT.split(" "):
            expected_token = token + " "
            expected_packet = create_packet_with_reasoning_delta(expected_token, 2)

            packet = next(answer_stream)
            assert_answer_stream_part_correct(packet, expected_packet)

        p9 = next(answer_stream)
        expected_packet9 = Packet(
            placement=create_placement(2),
            obj=ReasoningDone(),
        )
        assert_answer_stream_part_correct(p9, expected_packet9)

        CONTENT = [
            MockWebContent(
                title="Weather Now!",
                url="www.weathernow.com.au",
                content="The weather right now is sunny with a temperature of 22 degrees Celsius.",
            ),
            MockWebContent(
                title="Weather Official",
                url="www.weather.com.au",
                content="The current weather in Sydney is 20 degrees Celsius.",
            ),
        ]

        for content in CONTENT:
            mock_content.add_content(content)

        p10 = next(answer_stream)
        expected_packet10 = Packet(
            placement=create_placement(3),
            obj=OpenUrlStart(),
        )
        assert_answer_stream_part_correct(p10, expected_packet10)

        p11 = next(answer_stream)
        expected_packet11 = Packet(
            placement=create_placement(3),
            obj=OpenUrlUrls(
                urls=[content.url for content in CONTENT],
            ),
        )
        assert_answer_stream_part_correct(p11, expected_packet11)

        DOCS2 = [
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.weathernow.com.au",
                chunk_ind=0,
                semantic_identifier="Weather Now!",
                link="www.weathernow.com.au",
                blurb="Weather Now!",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.weather.com.au",
                chunk_ind=0,
                semantic_identifier="Weather Official",
                link="www.weather.com.au",
                blurb="Weather Official",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
        ]

        p12 = next(answer_stream)
        expected_packet12 = Packet(
            placement=create_placement(3),
            obj=OpenUrlDocuments(
                documents=DOCS2,
            ),
        )
        assert_answer_stream_part_correct(p12, expected_packet12)

        p13 = next(answer_stream)
        expected_packet13 = Packet(
            placement=create_placement(3),
            obj=SectionEnd(),
        )
        assert_answer_stream_part_correct(p13, expected_packet13)

        llm_thinking_response = (
            "I now know everything that I need to know. "
            "I can now answer the question."
        )

        mock_llm.add_response(
            LLMReasoningResponse(
                reasoning_tokens=[
                    (token + " ") for token in llm_thinking_response.split(" ")
                ]
            )
        )

        answer_response = (
            "The weather in Sydney is sunny with a temperature of 22 degrees Celsius."
        )
        answer_response_tokens = [(token + " ") for token in answer_response.split(" ")]
        mock_llm.add_response(
            LLMAnswerResponse(
                answer_tokens=answer_response_tokens,
            )
        )

        mock_llm.forward_till_end()

        p14 = next(answer_stream)
        expected_packet14 = Packet(
            placement=create_placement(4),
            obj=ReasoningStart(),
        )
        assert_answer_stream_part_correct(p14, expected_packet14)

        for token in llm_thinking_response.split(" "):
            expected_token = token + " "
            expected_packet = create_packet_with_reasoning_delta(expected_token, 4)

            packet = next(answer_stream)
            assert_answer_stream_part_correct(packet, expected_packet)

        p15 = next(answer_stream)
        expected_packet15 = Packet(
            placement=create_placement(4),
            obj=ReasoningDone(),
        )
        assert_answer_stream_part_correct(p15, expected_packet15)

        FINAL_DOCS = [
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.weather.com.au",
                chunk_ind=0,
                semantic_identifier="Weather Official",
                link="www.weather.com.au",
                blurb="The current weather in Sydney is 20 degrees Celsius.",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.weathernow.com.au",
                chunk_ind=0,
                semantic_identifier="Weather Now!",
                link="www.weathernow.com.au",
                blurb="The weather right now is sunny with a temperature of 22 degrees Celsius.",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.wc.com.au",
                chunk_ind=0,
                semantic_identifier="Weather Channel",
                link="www.wc.com.au",
                blurb="Morning is 10 degree Celsius, afternoon is 25 degrees Celsius.",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.weathernow.com.au",
                chunk_ind=0,
                semantic_identifier="Weather Now!",
                link="www.weathernow.com.au",
                blurb="Weather Now!",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
            SearchDoc(
                document_id="WEB_SEARCH_DOC_www.weather.com.au",
                chunk_ind=0,
                semantic_identifier="Weather Official",
                link="www.weather.com.au",
                blurb="Weather Official",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                match_highlights=[],
            ),
        ]

        p16 = next(answer_stream)
        expected_packet16 = Packet(
            placement=create_placement(5),
            obj=AgentResponseStart(
                final_documents=FINAL_DOCS,
            ),
        )
        assert_answer_stream_part_correct(p16, expected_packet16)

        for token in answer_response.split(" "):
            expected_token = token + " "
            expected_packet = create_packet_with_agent_response_delta(expected_token, 5)
            packet = next(answer_stream)
            assert_answer_stream_part_correct(packet, expected_packet)

        p17 = next(answer_stream)
        expected_packet17 = Packet(
            placement=create_placement(5),
            obj=OverallStop(),
        )
        assert_answer_stream_part_correct(p17, expected_packet17)
