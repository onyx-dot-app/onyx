"""Chat streams preserve final content, tool results, and execution identities."""

import json
from contextlib import nullcontext
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.chat.models import CreateChatSessionID
from onyx.configs.constants import DocumentSource
from onyx.db.models import ToolCall
from onyx.llm.model_request import UserMessage as RequestUserMessage
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.llm.models import ToolChoiceOptions
from onyx.prompts.chat_prompts import LAST_CYCLE_CITATION_REMINDER
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.streaming_models import (
    ImageGenerationFinal,
    OpenUrlDocuments,
    OverallStop,
    Packet,
    ReasoningDelta,
    SearchToolDocumentsDelta,
    SearchToolStart,
)
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_chat_session,
    final_answer,
    submit_query,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.mock_content_provider import (
    MockWebContent,
    use_mock_content_provider,
)
from tests.external_dependency_unit.mock_image_provider import (
    use_mock_image_generation_provider,
)
from tests.external_dependency_unit.mock_search_pipeline import (
    MockInternalSearchResult,
    use_mock_search_pipeline,
)
from tests.external_dependency_unit.mock_search_provider import (
    MockWebProvider,
    MockWebSearchResult,
    use_mock_web_provider,
)
from tests.unit.onyx.agents.fakes import ScriptedLLM

pytestmark = pytest.mark.usefixtures(
    "full_deployment_setup", "mock_external_deps", "default_llm_provider"
)


def tool_call(
    name: str, call_id: str, arguments: str, index: int = 0
) -> ChatCompletionDeltaToolCall:
    return ChatCompletionDeltaToolCall(
        id=call_id,
        index=index,
        function=ResponseFunctionCall(name=name, arguments=arguments),
    )


@pytest.mark.parametrize("create_session", [False, True])
def test_stream_chat_with_answer(
    db_session: Session,
    create_session: bool,
    make_test_user: MakeTestUser,
) -> None:
    user = make_test_user("stream_answer")
    session_id = None if create_session else create_chat_session(db_session, user).id
    llm = ScriptedLLM(
        [Delta(content="The capital of France is Paris.")], max_input_tokens=128000
    )
    with patch("onyx.chat.process_message.get_llm_for_persona", return_value=llm):
        parts = list(submit_query("What is the capital of France?", session_id, user))
    assert final_answer(parts) == "The capital of France is Paris."
    assert (
        any(isinstance(part, CreateChatSessionID) for part in parts) == create_session
    )
    ids = [part for part in parts if isinstance(part, MessageResponseIDInfo)]
    assert len(ids) == 1
    assert ids[0].user_message_id is not None
    assert ids[0].reserved_assistant_message_id > ids[0].user_message_id
    assert any(
        isinstance(part, Packet) and isinstance(part.obj, OverallStop) for part in parts
    )


def test_stream_chat_with_search_and_openurl_tools(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("stream_search")
    session = create_chat_session(db_session, user)
    url = "https://weather.example.com/sydney"
    llm = ScriptedLLM(
        [
            Delta(
                reasoning_content="I need current weather.",
                tool_calls=[
                    tool_call("web_search", "search", '{"queries":["Sydney weather"]}')
                ],
            ),
            Delta(
                reasoning_content="Read the weather source.",
                tool_calls=[tool_call("open_url", "open", json.dumps({"urls": [url]}))],
            ),
            Delta(content="Sydney is sunny [1]."),
        ],
        max_input_tokens=128000,
    )
    with (
        patch("onyx.chat.process_message.get_llm_for_persona", return_value=llm),
        use_mock_web_provider(db_session) as web,
        use_mock_content_provider() as content,
    ):
        web.add_results(
            "Sydney weather",
            [
                MockWebSearchResult(
                    title="Sydney weather", link=url, snippet="Sunny, 22 degrees."
                )
            ],
        )
        content.add_content(
            MockWebContent(
                title="Sydney weather",
                url=url,
                content="Sydney has sunny weather today with a temperature of 22 degrees Celsius.",
            )
        )
        parts = list(submit_query("What is the weather in Sydney?", session.id, user))
    assert "Sydney is sunny" in final_answer(parts)
    documents = [
        part.obj.documents
        for part in parts
        if isinstance(part, Packet)
        and isinstance(part.obj, (SearchToolDocumentsDelta, OpenUrlDocuments))
    ]
    assert len(documents) == 2
    assert all(docs[0].link == url for docs in documents)
    reasoning = [
        part.obj.reasoning
        for part in parts
        if isinstance(part, Packet) and isinstance(part.obj, ReasoningDelta)
    ]
    assert reasoning == ["I need current weather.", "Read the weather source."]
    assert len(llm.requests) == 3


@pytest.mark.parametrize("image_succeeds", [True, False])
def test_image_generation_tool(
    db_session: Session, make_test_user: MakeTestUser, image_succeeds: bool
) -> None:
    user = make_test_user("stream_image")
    session = create_chat_session(db_session, user)
    answer = (
        "Here is the image."
        if image_succeeds
        else "Image generation failed; here is what I found."
    )
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    tool_call(
                        "generate_image", "image", '{"prompt":"A dog on a rocketship"}'
                    )
                ]
            ),
            Delta(
                tool_calls=[tool_call("web_search", "web", '{"queries":["rockets"]}')]
            ),
            Delta(content=answer),
        ],
        max_input_tokens=128000,
    )
    with (
        patch("onyx.chat.process_message.get_llm_for_persona", return_value=llm),
        use_mock_image_generation_provider() as provider,
        use_mock_web_provider(db_session) as web,
        (
            nullcontext()
            if image_succeeds
            else patch(
                "tests.external_dependency_unit.mock_image_provider.MockImageGenerationProvider.generate_image",
                side_effect=RuntimeError("Image provider unavailable"),
            )
        ) as failed_generation,
    ):
        web.add_results(
            "rockets",
            [
                MockWebSearchResult(
                    title="Rockets",
                    link="https://rockets.example.com",
                    snippet="Rockets fly.",
                )
            ],
        )
        provider.add_image(
            "iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAIAAACRXR/mAAAAVElEQVR42u3WwQkAIAwDQOP+O9cN+lJUuHylcFApyWhTVc1rkkOzczwZLCwsrN9YuXXH+1lLxMLCwtpz5XV5fwsLC0uX1+WxsLCwdHldHgsLC+uxLK9hJFqMAN43AAAAAElFTkSuQmCC",
            0,
        )
        parts = list(submit_query("Draw a dog on a rocketship", session.id, user))
    assert final_answer(parts) == answer
    images = [
        part.obj.images
        for part in parts
        if isinstance(part, Packet) and isinstance(part.obj, ImageGenerationFinal)
    ]
    if image_succeeds:
        assert len(images) == 1
        assert len(images[0]) == 1
        assert images[0][0].url == "/api/chat/file/123"
    else:
        assert failed_generation is not None
        failed_generation.assert_called_once()
        assert not images
    # The image does not end the turn: the next step still offers tools.
    assert len(llm.requests) == 3
    assert llm.requests[1]["tool_choice"] == ToolChoiceOptions.AUTO
    assert "web_search" in {
        tool["function"]["name"] for tool in llm.requests[1]["tools"]
    }
    assert any(
        isinstance(part, Packet)
        and isinstance(part.obj, SearchToolDocumentsDelta)
        and any(doc.link == "https://rockets.example.com" for doc in part.obj.documents)
        for part in parts
    )


def test_parallel_internal_and_web_search_tool_calls(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("stream_parallel")
    session = create_chat_session(db_session, user)
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    tool_call(
                        "internal_search", "internal", '{"queries":["Q2 strategy"]}'
                    ),
                    tool_call("web_search", "web", '{"queries":["GDP forecast"]}', 1),
                ]
            ),
            Delta(content="The strategy matches the forecast."),
        ],
        max_input_tokens=128000,
    )
    with (
        patch("onyx.chat.process_message.get_llm_for_persona", return_value=llm),
        use_mock_web_provider(db_session) as web,
        use_mock_search_pipeline([DocumentSource.GOOGLE_DRIVE]) as internal,
    ):
        web.add_results(
            "GDP forecast",
            [
                MockWebSearchResult(
                    title="GDP forecast",
                    link="https://forecast.example.com",
                    snippet="Growth is expected.",
                )
            ],
        )
        internal.add_search_results(
            "Q2 strategy",
            [
                MockInternalSearchResult(
                    document_id="strategy",
                    source_type=DocumentSource.GOOGLE_DRIVE,
                    semantic_identifier="Q2 strategy",
                    chunk_ind=0,
                )
            ],
        )
        parts = list(
            submit_query(
                "Compare our Q2 strategy with the GDP forecast", session.id, user
            )
        )
    assert final_answer(parts) == "The strategy matches the forecast."
    tools = [
        part
        for part in parts
        if isinstance(part, Packet) and isinstance(part.obj, SearchToolStart)
    ]
    assert len(tools) == 2
    assert {
        part.obj.is_internet_search
        for part in tools
        if isinstance(part.obj, SearchToolStart)
    } == {True, False}
    assert len({part.placement.turn_index for part in tools}) == 1
    assert len({part.placement.tab_index for part in tools}) == 2
    documents = [
        part.obj.documents
        for part in parts
        if isinstance(part, Packet) and isinstance(part.obj, SearchToolDocumentsDelta)
    ]
    assert len(documents) == 2
    assert all(documents)


@pytest.mark.parametrize("calls_tool_at_cap", [False, True])
def test_chat_stops_tools_at_the_step_cap(
    db_session: Session, make_test_user: MakeTestUser, calls_tool_at_cap: bool
) -> None:
    user = make_test_user("stream_step_cap")
    session = create_chat_session(db_session, user)
    cap = 4
    # Definitions remain stable, but the final step cannot execute tools.
    queries = [f"topic {index}" for index in range(cap - 1)]
    llm = ScriptedLLM(
        [
            *(
                Delta(
                    tool_calls=[
                        tool_call(
                            "web_search",
                            f"search-{index}",
                            json.dumps({"queries": [q]}),
                        )
                    ]
                )
                for index, q in enumerate(queries)
            ),
            Delta(
                content="Answered at the cap.",
                tool_calls=[
                    tool_call("web_search", "blocked-at-cap", '{"queries":["blocked"]}')
                ]
                if calls_tool_at_cap
                else [],
            ),
        ],
        max_input_tokens=128000,
    )
    with (
        patch(
            "tests.external_dependency_unit.mock_search_provider.MockWebProvider.search",
            autospec=True,
            side_effect=MockWebProvider.search,
        ) as search,
        patch("onyx.chat.agent.MAX_LLM_CYCLES", cap),
        patch("onyx.chat.process_message.get_llm_for_persona", return_value=llm),
        use_mock_web_provider(db_session) as web,
    ):
        for query in queries:
            web.add_results(
                query,
                [
                    MockWebSearchResult(
                        title=query,
                        link=f"https://example.com/{query.replace(' ', '-')}",
                        snippet=f"About {query}.",
                    )
                ],
            )
        parts = list(submit_query("Cover every topic.", session.id, user))
    assert final_answer(parts) == "Answered at the cap."
    assert len(llm.requests) == cap
    assert all(
        request["tool_choice"] == ToolChoiceOptions.AUTO and request["tools"]
        for request in llm.requests[:-1]
    )
    last = llm.requests[-1]
    assert last["tools"] == llm.requests[0]["tools"]
    assert last["tool_choice"] == ToolChoiceOptions.NONE
    assert any(
        isinstance(message, RequestUserMessage)
        and isinstance(message.content, str)
        and LAST_CYCLE_CITATION_REMINDER in message.content
        for message in last["prompt"]
    )
    saved_calls = (
        db_session.query(ToolCall).filter(ToolCall.chat_session_id == session.id).all()
    )
    assert len(saved_calls) == cap - 1 + int(calls_tool_at_cap)
    assert [call.args[1] for call in search.call_args_list] == queries
