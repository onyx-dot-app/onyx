"""Chat streams preserve final content, tool results, and execution identities."""

import json
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.chat.models import CreateChatSessionID
from onyx.configs.constants import DocumentSource
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
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
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_chat_session,
    final_answer,
    submit_query,
)
from tests.external_dependency_unit.conftest import create_test_user
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
    MockWebSearchResult,
    use_mock_web_provider,
)
from tests.unit.onyx.agents.fakes import ScriptedLLM

pytestmark = pytest.mark.usefixtures("full_deployment_setup", "mock_external_deps")


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
) -> None:
    ensure_default_llm_provider(db_session)
    user = create_test_user(db_session, email_prefix="stream_answer")
    session_id = None if create_session else create_chat_session(db_session, user).id
    llm = ScriptedLLM(
        [Delta(content="The capital of France is Paris.")], max_input_tokens=128000
    )
    with patch("onyx.chat.prepare.get_llm_for_persona", return_value=llm):
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


def test_stream_chat_with_search_and_openurl_tools(db_session: Session) -> None:
    ensure_default_llm_provider(db_session)
    user = create_test_user(db_session, email_prefix="stream_search")
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
        patch("onyx.chat.prepare.get_llm_for_persona", return_value=llm),
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


def test_image_generation_tool(db_session: Session) -> None:
    ensure_default_llm_provider(db_session)
    user = create_test_user(db_session, email_prefix="stream_image")
    session = create_chat_session(db_session, user)
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    tool_call(
                        "generate_image", "image", '{"prompt":"A dog on a rocketship"}'
                    )
                ]
            ),
            Delta(content="Here is the image."),
        ],
        max_input_tokens=128000,
    )
    with (
        patch("onyx.chat.prepare.get_llm_for_persona", return_value=llm),
        use_mock_image_generation_provider() as provider,
    ):
        provider.add_image(
            "iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAIAAACRXR/mAAAAVElEQVR42u3WwQkAIAwDQOP+O9cN+lJUuHylcFApyWhTVc1rkkOzczwZLCwsrN9YuXXH+1lLxMLCwtpz5XV5fwsLC0uX1+WxsLCwdHldHgsLC+uxLK9hJFqMAN43AAAAAElFTkSuQmCC",
            0,
        )
        parts = list(submit_query("Draw a dog on a rocketship", session.id, user))
    assert final_answer(parts) == "Here is the image."
    images = [
        part.obj.images
        for part in parts
        if isinstance(part, Packet) and isinstance(part.obj, ImageGenerationFinal)
    ]
    assert len(images) == 1
    assert len(images[0]) == 1
    assert images[0][0].url == "/api/chat/file/123"


def test_parallel_internal_and_web_search_tool_calls(db_session: Session) -> None:
    ensure_default_llm_provider(db_session)
    user = create_test_user(db_session, email_prefix="stream_parallel")
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
        patch("onyx.chat.prepare.get_llm_for_persona", return_value=llm),
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
