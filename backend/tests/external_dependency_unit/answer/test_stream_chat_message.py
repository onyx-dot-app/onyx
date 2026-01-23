from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.chat.models import CreateChatSessionID
from onyx.chat.models import MessageResponseIDInfo
from onyx.configs.constants import DocumentSource
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
from onyx.server.query_and_chat.streaming_models import ReasoningDone
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.server.query_and_chat.streaming_models import TopLevelBranching
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.answer.stream_test_assertions import (
    assert_answer_stream_part_correct,
)
from tests.external_dependency_unit.answer.stream_test_builder import StreamTestBuilder
from tests.external_dependency_unit.answer.stream_test_utils import create_chat_session
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_packet_with_agent_response_delta,
)
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_packet_with_reasoning_delta,
)
from tests.external_dependency_unit.answer.stream_test_utils import create_placement
from tests.external_dependency_unit.answer.stream_test_utils import (
    mock_web_content_to_search_doc,
)
from tests.external_dependency_unit.answer.stream_test_utils import (
    mock_web_search_result_to_search_doc,
)
from tests.external_dependency_unit.answer.stream_test_utils import submit_query
from tests.external_dependency_unit.answer.stream_test_utils import tokenise
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
from tests.external_dependency_unit.mock_llm import use_mock_llm
from tests.external_dependency_unit.mock_search_pipeline import MockInternalSearchResult
from tests.external_dependency_unit.mock_search_pipeline import use_mock_search_pipeline
from tests.external_dependency_unit.mock_search_provider import MockWebSearchResult
from tests.external_dependency_unit.mock_search_provider import use_mock_web_provider


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
        handler = StreamTestBuilder(llm_controller=mock_llm)

        handler.add_response(LLMAnswerResponse(answer_tokens=answer_tokens))

        chat_session = create_chat_session(db_session=db_session, user=test_user)

        answer_stream = submit_query(
            query=query,
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

        handler.expect_agent_response(
            answer_tokens=answer_tokens,
            turn_index=0,
        ).run_and_validate(stream=answer_stream)

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
        handler = StreamTestBuilder(llm_controller=mock_llm)

        handler.add_response(LLMAnswerResponse(answer_tokens=tokens))

        answer_stream = submit_query(
            query=query,
            chat_session_id=None,
            db_session=db_session,
            user=test_user,
        )

        assert_answer_stream_part_correct(
            received=next(answer_stream),
            expected=CreateChatSessionID(
                chat_session_id=UUID("123e4567-e89b-12d3-a456-426614174000")
            ),
        )

        assert_answer_stream_part_correct(
            received=next(answer_stream),
            expected=MessageResponseIDInfo(
                user_message_id=1,
                reserved_assistant_message_id=2,
            ),
        )

        handler.expect_agent_response(
            answer_tokens=tokens,
            turn_index=0,
        ).run_and_validate(stream=answer_stream)

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

    REASONING_RESPONSE_1 = (
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

    REASONING_RESPONSE_2 = "I like weathernow and the official weather site"

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
        handler = StreamTestBuilder(
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
            LLMReasoningResponse(reasoning_tokens=tokenise(REASONING_RESPONSE_1))
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
                for token in tokenise(REASONING_RESPONSE_1)
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
            LLMReasoningResponse(reasoning_tokens=tokenise(REASONING_RESPONSE_2))
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
                for token in tokenise(REASONING_RESPONSE_2)
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
        ).expect_agent_response(
            answer_tokens=tokenise(ANSWER_RESPONSE_1),
            turn_index=5,
            final_documents=[
                mock_web_search_result_to_search_doc(result) for result in RESULTS1
            ]
            + [mock_web_search_result_to_search_doc(result) for result in RESULTS2]
            + [mock_web_content_to_search_doc(content) for content in CONTENT1],
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
    )
    # Heartbeat interval is 5 seconds. A delay of 8 seconds ensures exactly 2 heartbeats:
    IMAGE_DELAY = 8.0

    ANSWER_RESPONSE = "Here is a dog on a rocketship"

    with (
        use_mock_llm() as mock_llm,
        use_mock_image_generation_provider() as mock_image_gen,
    ):
        handler = StreamTestBuilder(
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


def test_parallel_internal_and_web_search_tool_calls(
    db_session: Session,
    full_deployment_setup: None,
    mock_external_deps: None,
) -> None:
    """
    User asks a question
    LLM does some thinking
    LLM runs parallel tool calls for internal & web search

    -> Interal Search Branch performs seach + read ~10 documents
    -> Web Search: Searches the web for information

    LLM reads web documents
    LLM does thinking across all results
    LLM reads one more website
    LLM does more thinking
    LLM generates answer
    """
    ensure_default_llm_provider(db_session)
    test_user = create_test_user(
        db_session, email_prefix="test_parallel_internal_and_web_search_tool_calls"
    )

    AVALIABLE_CONNECTORS = [
        DocumentSource.GOOGLE_DRIVE,
        DocumentSource.CONFLUENCE,
        DocumentSource.LINEAR,
        DocumentSource.FIREFLIES,
    ]

    QUERY = "How will forecasts against 2026 global GDP growth affect our Q2 strategy?"

    THINKING_RESPONSE_1 = (
        "I need to build more context around the user's query to answer it. "
        "I should look at GDP growth projections for 2026. "
        "I should also look at what the Q2 strategy is and what projects are included. "
        "I should perform both web and internal searches in parallel to get information efficiently."
    )

    WEB_QUERIES_1 = [
        "2026 global GDP growth projections",
        "GDP growth 2026",
        "GDP forecast 2026",
    ]

    WEB_RESULTS_1 = {
        WEB_QUERIES_1[0]: [
            MockWebSearchResult(
                title="World Economic Outlook Update, January 2026",
                link="https://www.imf.org/weo/issues/2026/01/19/world-economic-outlook-update-january-2026",
                snippet="Global growth is projected at 3.3 percent for 2026 and 3.2 percent for 2027...",
            ),
            MockWebSearchResult(
                title="IMF sees steady global growth in 2026 as AI boom offsets ...",
                link="https://www.reuters.com/article/us-world-economy-imf-idUSKBN2JU23E",
                snippet="IMF forecasts 2026 global GDP growth at 3.3% even with stronger 2025 performance",
            ),
            MockWebSearchResult(
                title="The Global Economy Is Forecast to Post...",
                link="https://www.goldmansachs.com/insights/articles/123",
                snippet="Global GDP is projected by Goldman Sachs Research to increase 2.8% in 2026",
            ),
        ],
        WEB_QUERIES_1[1]: [
            MockWebSearchResult(
                title="US third-quarter economic growth revised  slightly higher",
                link="https://www.reuters.com/word/us-third-quarter-eco",
                snippet="Gross domestic product increased at an upwardly revised 4.4% annualized rate, the ...",
            ),
            MockWebSearchResult(
                title="US GDP Growth Is Projected to Outperform Economist ...",
                link="https://www.goldmansachs.com/insights/articles/321",
                snippet="US GDP is forecast to expand 2.5% in 2026 (fourth quarter, yoy), versus",
            ),
            MockWebSearchResult(
                title="Gross Domestic Product",
                link="https://www.bea.gov/data/gdp/gross-domestic-product",
                snippet="Real gross domestic product (GDP) increased at an annual rate of 4.4 percent in the third quarter",
            ),
        ],
        WEB_QUERIES_1[2]: [
            MockWebSearchResult(
                title="World Economic Outlook Update, January 2026",
                link="https://www.imf.org/web/issues/2026/01/19/world-economic-outlook-update-january-2026",
                snippet="Global growth is projected at 3.3 percent for 2026 and 3.2 percent for 2027...",
            ),
            MockWebSearchResult(
                title="US GDP Growth Is Projected to Outperform Economist ...",
                link="https://www.goldmansachs.com/insights/articles/321",
                snippet="US GDP is forecast to expand 2.5% in 2026 (fourth quarter, yoy), versus",
            ),
            MockWebSearchResult(
                title="Our economic outlook for the United States - Vanguard",
                link="https://corporate.vanguard.com/content/corp/vemo",
                snippet="We expect strong capital investment to remain a principal strength in the year ahead",
            ),
        ],
    }

    INTERNAL_QUERIES_1 = ["Q2 strategy 2026", "GDP growth 2026 projects", "Q2 projects"]

    INTERNAL_RESULTS_1 = {
        INTERNAL_QUERIES_1[0]: [
            MockInternalSearchResult(
                document_id="123456789",
                source_type=DocumentSource.GOOGLE_DRIVE,
                semantic_identifier="Q2 strategy 2026",
                chunk_ind=11,
            ),
            MockInternalSearchResult(
                document_id="732190732173",
                source_type=DocumentSource.FIREFLIES,
                semantic_identifier="What we think is going to happen in Q2",
                chunk_ind=5,
            ),
            MockInternalSearchResult(
                document_id="12389123219",
                source_type=DocumentSource.CONFLUENCE,
                semantic_identifier="Strategy roadmap for Q2 2026",
                chunk_ind=7,
            ),
        ],
        INTERNAL_QUERIES_1[1]: [
            MockInternalSearchResult(
                document_id="123123",
                source_type=DocumentSource.LINEAR,
                semantic_identifier="GDP growth 2026 projects",
                chunk_ind=13,
            )
        ],
        INTERNAL_QUERIES_1[2]: [
            MockInternalSearchResult(
                document_id="98823643243",
                source_type=DocumentSource.GOOGLE_DRIVE,
                semantic_identifier="Full list of Q2 projects",
                chunk_ind=1,
            )
        ],
    }

    OPEN_URL_URLS_1 = [
        WEB_RESULTS_1[WEB_QUERIES_1[0]][0].link,
        WEB_RESULTS_1[WEB_QUERIES_1[0]][2].link,
        WEB_RESULTS_1[WEB_QUERIES_1[2]][0].link,
    ]

    OPEN_URL_DOCUMENTS_1 = [
        MockWebContent(
            title=WEB_RESULTS_1[WEB_QUERIES_1[0]][0].title,
            url=WEB_RESULTS_1[WEB_QUERIES_1[0]][0].link,
            content="Global growth is projected at 3.3 percent for 2026 and 3.2 percent for 2027...",
        ),
        MockWebContent(
            title=WEB_RESULTS_1[WEB_QUERIES_1[0]][2].title,
            url=WEB_RESULTS_1[WEB_QUERIES_1[0]][2].link,
            content="Global growth is projected at 3.3 percent for 2026 and 3.2 percent for 2027...",
        ),
        MockWebContent(
            title=WEB_RESULTS_1[WEB_QUERIES_1[2]][0].title,
            url=WEB_RESULTS_1[WEB_QUERIES_1[2]][0].link,
            content="Global growth is projected at 3.3 percent for 2026 and 3.2 percent for 2027...",
        ),
    ]

    THINKING_RESPONSE_2 = (
        "I now have a clear picture of the 2026 global GDP projections and the Q2 strategy. "
        "I would like to now about the outperform expections though..."
    )

    OPEN_URL_URLS_2 = [WEB_RESULTS_1[WEB_QUERIES_1[1]][1].link]
    OPEN_URL_DOCUMENTS_2 = [
        MockWebContent(
            title=WEB_RESULTS_1[WEB_QUERIES_1[1]][1].title,
            url=WEB_RESULTS_1[WEB_QUERIES_1[1]][1].link,
            content="US GDP is forecast to expand 2.5% in 2026 (fourth quarter, yoy), versus",
        )
    ]

    REASONING_RESPONSE_3 = (
        "I now have all the information I need to answer the user's question."
    )

    ANSWER_RESPONSE = (
        "We will have to change around some of our projects to accomodate the outperform expections. "
        "We should focus on aggresive expansion projects and prioritize them over cost-cutting initiatives."
    )

    expected_web_docs = []
    seen_web_results = set()
    for web_results in WEB_RESULTS_1.values():
        for web_result in web_results:
            key = (web_result.title, web_result.link)
            if key in seen_web_results:
                continue
            seen_web_results.add(key)
            expected_web_docs.append(mock_web_search_result_to_search_doc(web_result))

    expected_internal_docs = []
    seen_internal_results = set()
    for internal_results in INTERNAL_RESULTS_1.values():
        for internal_result in internal_results:
            key = (internal_result.semantic_identifier, internal_result.document_id)
            if key in seen_internal_results:
                continue
            seen_internal_results.add(key)
            expected_internal_docs.append(internal_result.to_search_doc())

    with (
        use_mock_llm() as mock_llm,
        use_mock_search_pipeline(
            connectors=AVALIABLE_CONNECTORS
        ) as mock_search_pipeline,
        use_mock_web_provider(db_session) as mock_web,
        use_mock_content_provider() as mock_content,
    ):
        for query, web_results in WEB_RESULTS_1.items():
            mock_web.add_results(query, web_results)

        for query, internal_results in INTERNAL_RESULTS_1.items():
            mock_search_pipeline.add_search_results(query, internal_results)

        handler = StreamTestBuilder(
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
        handler.add_response(
            LLMReasoningResponse(
                reasoning_tokens=tokenise(THINKING_RESPONSE_1),
            )
        ).add_responses_together(
            LLMToolCallResponse(
                tool_name="internal_search",
                tool_call_id="123",
                tool_call_argument_tokens=[json.dumps({"queries": INTERNAL_QUERIES_1})],
            ),
            LLMToolCallResponse(
                tool_name="web_search",
                tool_call_id="321",
                tool_call_argument_tokens=[json.dumps({"queries": WEB_QUERIES_1})],
            ),
        ).expect_reasoning(
            reasoning_tokens=tokenise(THINKING_RESPONSE_1),
            turn_index=0,
        ).expect(
            Packet(
                placement=create_placement(1),
                obj=TopLevelBranching(
                    num_parallel_branches=2,
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1, 0),
                obj=SearchToolStart(
                    is_internet_search=False,
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1, 1),
                obj=SearchToolStart(
                    is_internet_search=True,
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1, 0),
                obj=SearchToolQueriesDelta(
                    queries=INTERNAL_QUERIES_1 + [QUERY],
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1, 0),
                obj=SearchToolDocumentsDelta(
                    documents=expected_internal_docs,
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1, 0),
                obj=SectionEnd(),
            )
        ).expect(
            Packet(
                placement=create_placement(1, 1),
                obj=SearchToolQueriesDelta(
                    queries=WEB_QUERIES_1,
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1, 1),
                obj=SearchToolDocumentsDelta(
                    documents=expected_web_docs,
                ),
            )
        ).expect(
            Packet(
                placement=create_placement(1, 1),
                obj=SectionEnd(),
            )
        ).run_and_validate(
            stream=answer_stream
        )

        # LLM Stream Response 2
        for content in OPEN_URL_DOCUMENTS_1:
            mock_content.add_content(content)

        handler.add_response(
            LLMToolCallResponse(
                tool_name="open_url",
                tool_call_id="456",
                tool_call_argument_tokens=[json.dumps({"urls": OPEN_URL_URLS_1})],
            )
        ).expect(
            Packet(
                placement=create_placement(2, 0),
                obj=OpenUrlStart(),
            ),
            forward=2,  # Need both header + argument tokens for the tool call
        ).expect(
            Packet(
                placement=create_placement(2, 0),
                obj=OpenUrlUrls(urls=OPEN_URL_URLS_1),
            ),
            forward=False,
        ).expect(
            Packet(
                placement=create_placement(2, 0),
                obj=OpenUrlDocuments(
                    documents=[
                        mock_web_content_to_search_doc(content)
                        for content in OPEN_URL_DOCUMENTS_1
                    ]
                ),
            ),
            forward=False,
        ).expect(
            Packet(
                placement=create_placement(2, 0),
                obj=SectionEnd(),
            ),
            forward=False,
        ).run_and_validate(
            stream=answer_stream
        )

        # LLM Stream Response 3
        for content in OPEN_URL_DOCUMENTS_2:
            mock_content.add_content(content)

        handler.add_response(
            LLMReasoningResponse(
                reasoning_tokens=tokenise(THINKING_RESPONSE_2),
            )
        ).add_response(
            LLMToolCallResponse(
                tool_name="open_url",
                tool_call_id="789",
                tool_call_argument_tokens=[json.dumps({"urls": OPEN_URL_URLS_2})],
            )
        ).expect_reasoning(
            reasoning_tokens=tokenise(THINKING_RESPONSE_2),
            turn_index=3,
        ).expect(
            Packet(
                placement=create_placement(4),
                obj=OpenUrlStart(),
            )
        ).expect(
            Packet(placement=create_placement(4), obj=OpenUrlUrls(urls=OPEN_URL_URLS_2))
        ).expect(
            Packet(
                placement=create_placement(4),
                obj=OpenUrlDocuments(
                    documents=[
                        mock_web_content_to_search_doc(content)
                        for content in OPEN_URL_DOCUMENTS_2
                    ]
                ),
            ),
            forward=False,
        ).expect(
            Packet(
                placement=create_placement(4),
                obj=SectionEnd(),
            )
        ).run_and_validate(
            stream=answer_stream
        )

        # LLM Stream Response 4
        handler.add_response(
            LLMReasoningResponse(
                reasoning_tokens=tokenise(REASONING_RESPONSE_3),
            )
        ).add_response(
            LLMAnswerResponse(
                answer_tokens=tokenise(ANSWER_RESPONSE),
            )
        ).expect_reasoning(
            reasoning_tokens=tokenise(REASONING_RESPONSE_3),
            turn_index=5,
        ).expect_agent_response(
            answer_tokens=tokenise(ANSWER_RESPONSE),
            turn_index=6,
            final_documents=expected_internal_docs
            + expected_web_docs
            + [
                mock_web_content_to_search_doc(content)
                for content in OPEN_URL_DOCUMENTS_1
            ]
            + [
                mock_web_content_to_search_doc(content)
                for content in OPEN_URL_DOCUMENTS_2
            ],
        ).run_and_validate(
            stream=answer_stream
        )

        # End stream
        with pytest.raises(StopIteration):
            next(answer_stream)
