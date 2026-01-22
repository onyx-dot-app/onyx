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
from onyx.server.query_and_chat.streaming_models import GeneratedImage
from onyx.server.query_and_chat.streaming_models import ImageGenerationFinal
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolHeartbeat
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
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
from tests.external_dependency_unit.mock_image_provider import (
    use_mock_image_generation_provider,
)
from tests.external_dependency_unit.mock_llm import LLMAnswerResponse
from tests.external_dependency_unit.mock_llm import LLMReasoningResponse
from tests.external_dependency_unit.mock_llm import LLMToolCallResponse
from tests.external_dependency_unit.mock_llm import MockLLMController
from tests.external_dependency_unit.mock_llm import use_mock_llm
from tests.external_dependency_unit.mock_search_provider import MockWebSearchResult
from tests.external_dependency_unit.mock_search_provider import use_mock_web_provider


class HandleCase:
    def __init__(self, llm_controller: MockLLMController):
        self._llm_controller = llm_controller

        # List of (expected_packet, forward_count) tuples
        self._expected_packets_queue: list[tuple[Packet, int]] = []

    def add_response(self, response) -> HandleCase:
        self._llm_controller.add_response(response)

        return self

    def expect(self, expected_pkt, forward: int | bool = True) -> HandleCase:
        """
        Add an expected packet to the queue.

        Args:
            expected_pkt: The packet to expect
            forward: Number of tokens to forward before expecting this packet.
                     True = 1 token, False = 0 tokens, int = that many tokens.
        """
        forward_count = 1 if forward is True else (0 if forward is False else forward)
        self._expected_packets_queue.append((expected_pkt, forward_count))

        return self

    def expect_packets(self, packets, forward: int | bool = True) -> HandleCase:
        """
        Add multiple expected packets to the queue.

        Args:
            packets: List of packets to expect
            forward: Number of tokens to forward before expecting EACH packet.
                     True = 1 token per packet, False = 0 tokens, int = that many tokens per packet.
        """
        forward_count = 1 if forward is True else (0 if forward is False else forward)
        for pkt in packets:
            self._expected_packets_queue.append((pkt, forward_count))

        return self

    def run_and_validate(self, stream: Iterator[AnswerStreamPart]) -> None:
        while self._expected_packets_queue:
            expected_pkt, forward_count = self._expected_packets_queue.pop(0)
            if forward_count > 0:
                self._llm_controller.forward(forward_count)
            received_pkt = next(stream)

            assert_answer_stream_part_correct(received_pkt, expected_pkt)


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


def tokenise(test: str) -> list[str]:
    return [(token + " ") for token in test.split(" ")]


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
        elif isinstance(r_packet.obj, ImageGenerationFinal):
            assert is_image_generation_final_equal(r_packet.obj, e_packet.obj)
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


def is_image_generation_final_equal(
    received: ImageGenerationFinal,
    expected: ImageGenerationFinal,
) -> bool:
    """
    What we care about:
     - Number of images are the same
     - On each image, url and file_id are aligned such that url=/api/chat/file/{file_id}
     - Revised prompt is expected
     - Shape is expected
    """
    if len(received.images) != len(expected.images):
        return False

    for received_image, expected_image in zip(received.images, expected.images):
        if received_image.url != f"/api/chat/file/{received_image.file_id}":
            return False
        if received_image.revised_prompt != expected_image.revised_prompt:
            return False
        if received_image.shape != expected_image.shape:
            return False
    return True


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

    answer_tokens = tokenise(answer)

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

        for token in tokenise(answer):
            expected_packet = create_packet_with_agent_response_delta(token, 0)

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
    ensure_default_llm_provider(db_session)
    test_user = create_test_user(
        db_session, email_prefix="test_stream_chat_with_search_tool"
    )

    QUERY = "What is the weather in Sydney?"

    REASOING_RESPONSE_1 = (
        "I need to perform a web search to get current weather details. "
        "I can use the search tool to do this."
    )

    WEB_QUERY_1 = "weather in sydney"
    WEB_QUERY_2 = "current weather in sydney"

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

    REASOING_RESPONSE_2 = "I like weathernow and the official weather site"

    QUERY_URLS_1 = ["www.weathernow.com.au", "www.weather.com.au"]

    CONTENT1 = [
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

    REASONING_RESPONSE_3 = (
        "I now know everything that I need to know. " "I can now answer the question."
    )

    ANSWER_RESPONSE_1 = (
        "The weather in Sydney is sunny with a temperature of 22 degrees celsius."
    )

    with (
        use_mock_llm() as mock_llm,
        use_mock_web_provider(db_session) as mock_web,
        use_mock_content_provider() as mock_content,
    ):
        handler = HandleCase(
            llm_controller=mock_llm,
        )

        chat_session = create_chat_session(db_session=db_session, user=test_user)

        answer_stream = submit_query(
            query=QUERY,
            chat_session_id=chat_session.id,
            db_session=db_session,
            user=test_user,
        )

        assert_answer_stream_part_correct(
            received=next(answer_stream),
            expected=MessageResponseIDInfo(
                user_message_id=1,
                reserved_assistant_message_id=1,
            ),
        )

        # LLM Stream Response 1
        mock_web.add_results(WEB_QUERY_1, RESULTS1)
        mock_web.add_results(WEB_QUERY_2, RESULTS2)

        handler.add_response(
            LLMReasoningResponse(reasoning_tokens=tokenise(REASOING_RESPONSE_1))
        ).add_response(
            LLMToolCallResponse(
                tool_name="web_search",
                tool_call_id="123",
                tool_call_argument_tokens=[
                    json.dumps({"queries": [WEB_QUERY_1, WEB_QUERY_2]})
                ],
            )
        ).expect(
            Packet(
                placement=create_placement(0),
                obj=ReasoningStart(),
            )
        ).expect_packets(
            [
                create_packet_with_reasoning_delta(token, 0)
                for token in tokenise(REASOING_RESPONSE_1)
            ]
        ).expect(
            Packet(placement=create_placement(0), obj=ReasoningDone())
        ).expect(
            Packet(
                placement=create_placement(1),
                obj=SearchToolStart(
                    is_internet_search=True,
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1),
                obj=SearchToolQueriesDelta(
                    queries=[WEB_QUERY_1, WEB_QUERY_2],
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1),
                obj=SearchToolDocumentsDelta(
                    documents=[
                        mock_web_search_result_to_search_doc(result)
                        for result in RESULTS1
                    ]
                    + [
                        mock_web_search_result_to_search_doc(result)
                        for result in RESULTS2
                    ]
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1),
                obj=SectionEnd(),
            )
        ).run_and_validate(
            stream=answer_stream
        )

        # LLM Stream Response 2
        for content in CONTENT1:
            mock_content.add_content(content)

        handler.add_response(
            LLMReasoningResponse(reasoning_tokens=tokenise(REASOING_RESPONSE_2))
        ).add_response(
            LLMToolCallResponse(
                tool_name="open_url",
                tool_call_id="123",
                tool_call_argument_tokens=[json.dumps({"urls": QUERY_URLS_1})],
            )
        ).expect(
            Packet(
                placement=create_placement(2),
                obj=ReasoningStart(),
            )
        ).expect_packets(
            [
                create_packet_with_reasoning_delta(token, 2)
                for token in tokenise(REASOING_RESPONSE_2)
            ]
        ).expect(
            Packet(
                placement=create_placement(2),
                obj=ReasoningDone(),
            )
        ).expect(
            Packet(
                placement=create_placement(3),
                obj=OpenUrlStart(),
            )
        ).expect(
            Packet(
                placement=create_placement(3),
                obj=OpenUrlUrls(urls=[content.url for content in CONTENT1]),
            )
        ).expect(
            Packet(
                placement=create_placement(3),
                obj=OpenUrlDocuments(
                    documents=[
                        mock_web_content_to_search_doc(content) for content in CONTENT1
                    ]
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(3),
                obj=SectionEnd(),
            )
        ).run_and_validate(
            stream=answer_stream
        )

        # LLM Stream Response 3
        handler.add_response(
            LLMReasoningResponse(reasoning_tokens=tokenise(REASONING_RESPONSE_3))
        ).add_response(
            LLMAnswerResponse(answer_tokens=tokenise(ANSWER_RESPONSE_1))
        ).expect(
            Packet(
                placement=create_placement(4),
                obj=ReasoningStart(),
            )
        ).expect_packets(
            [
                create_packet_with_reasoning_delta(token, 4)
                for token in tokenise(REASONING_RESPONSE_3)
            ]
        ).expect(
            Packet(
                placement=create_placement(4),
                obj=ReasoningDone(),
            )
        ).expect(
            Packet(
                placement=create_placement(5),
                obj=AgentResponseStart(
                    final_documents=[
                        mock_web_search_result_to_search_doc(result)
                        for result in RESULTS1
                    ]
                    + [
                        mock_web_search_result_to_search_doc(result)
                        for result in RESULTS2
                    ]
                    + [mock_web_content_to_search_doc(content) for content in CONTENT1]
                ),
            )
        ).expect_packets(
            [
                create_packet_with_agent_response_delta(token, 5)
                for token in tokenise(ANSWER_RESPONSE_1)
            ]
        ).expect(
            Packet(
                placement=create_placement(5),
                obj=OverallStop(),
            )
        ).run_and_validate(
            stream=answer_stream
        )

        with pytest.raises(StopIteration):
            next(answer_stream)


def test_image_generation_tool_no_reasoning(
    db_session: Session,
    full_deployment_setup: None,
    mock_external_deps: None,
) -> None:
    ensure_default_llm_provider(db_session)
    test_user = create_test_user(db_session, email_prefix="test_image_generation_tool")

    QUERY = "Create me an image of a dog on a rocketship"

    IMAGE_DATA = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfF"
        "cSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )  # pragma: allowlist secret
    # Heartbeat interval is 5 seconds. A delay of 8 seconds ensures exactly 2 heartbeats:
    IMAGE_DELAY = 8.0

    ANSWER_RESPONSE = "Here is a dog on a rocketship"

    with (
        use_mock_llm() as mock_llm,
        use_mock_image_generation_provider() as mock_image_gen,
    ):
        handler = HandleCase(
            llm_controller=mock_llm,
        )

        chat_session = create_chat_session(db_session=db_session, user=test_user)

        answer_stream = submit_query(
            query=QUERY,
            chat_session_id=chat_session.id,
            db_session=db_session,
            user=test_user,
        )

        assert_answer_stream_part_correct(
            received=next(answer_stream),
            expected=MessageResponseIDInfo(
                user_message_id=1,
                reserved_assistant_message_id=1,
            ),
        )

        # LLM Stream Response 1
        mock_image_gen.add_image(IMAGE_DATA, IMAGE_DELAY)
        mock_llm.set_max_timeout(
            IMAGE_DELAY + 5.0
        )  # Give enough buffer for image generation

        # The LLMToolCallResponse has 2 tokens (1 for tool name/id + 1 for arguments).
        # We need to forward all 2 tokens before the tool starts executing and emitting packets.
        # The tool then emits: start, heartbeats (during image generation), final, and section end.
        handler.add_response(
            LLMToolCallResponse(
                tool_name="generate_image",
                tool_call_id="123",
                tool_call_argument_tokens=[json.dumps({"prompt": QUERY})],
            )
        ).expect(
            Packet(
                placement=create_placement(0),
                obj=ImageGenerationToolStart(),
            ),
            forward=2,  # Forward both tool call tokens before expecting first packet
        ).expect_packets(
            [
                Packet(
                    placement=create_placement(0),
                    obj=ImageGenerationToolHeartbeat(),
                )
            ]
            * 2,
            forward=False,
        ).expect(
            Packet(
                placement=create_placement(0),
                obj=ImageGenerationFinal(
                    images=[
                        GeneratedImage(
                            file_id="123",
                            url="/api/chat/file/123",
                            revised_prompt=QUERY,
                            shape="square",
                        )
                    ]
                ),
            ),
            forward=False,
        ).expect(
            Packet(
                placement=create_placement(0),
                obj=SectionEnd(),
            ),
            forward=False,
        ).run_and_validate(
            stream=answer_stream
        )

        # LLM Stream Response 2 - the answer comes after the tool call, so turn_index=1
        handler.add_response(
            LLMAnswerResponse(
                answer_tokens=tokenise(ANSWER_RESPONSE),
            )
        ).expect(
            Packet(
                placement=create_placement(1),
                obj=AgentResponseStart(final_documents=None),
            )
        ).expect_packets(
            [
                create_packet_with_agent_response_delta(token, 1)
                for token in tokenise(ANSWER_RESPONSE)
            ]
        ).expect(
            Packet(
                placement=create_placement(1),
                obj=OverallStop(),
            )
        ).run_and_validate(
            stream=answer_stream
        )

        with pytest.raises(StopIteration):
            next(answer_stream)
