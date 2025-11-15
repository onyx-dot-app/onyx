"""
Unit tests for fast_chat_turn that exercise the new agent framework query loop.
"""

from collections.abc import Iterator
from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.chat.models import PromptConfig
from onyx.chat.stop_signal_checker import set_fence
from onyx.chat.turn.fast_chat_turn import _fast_chat_turn_core
from onyx.chat.turn.fast_chat_turn import fast_chat_turn
from onyx.chat.turn.infra.chat_turn_event_stream import unified_event_stream
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.chat.turn.models import FetchedDocumentCacheEntry
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.llm.model_response import Delta
from onyx.llm.model_response import FunctionCall
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from tests.unit.onyx.agents.agent_framework.conftest import FakeTool
from tests.unit.onyx.chat.turn.utils import create_test_inference_section
from tests.unit.onyx.chat.turn.utils import create_test_iteration_answer


class ScriptedFakeLLM(LLM):
    """LLM double that returns a different stream per invocation."""

    def __init__(self, scripted_responses: list[list[ModelResponseStream]]) -> None:
        self._scripts = scripted_responses
        self._config = LLMConfig(
            model_provider="fake-provider",
            model_name="fake-model",
            temperature=0.0,
            max_input_tokens=8192,
        )
        self._call_index = 0
        self.stream_calls: list[dict[str, Any]] = []

    @property
    def config(self) -> LLMConfig:
        return self._config

    def log_model_configs(self) -> None:
        return None

    def _invoke_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict[str, Any] | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        raise AssertionError("ScriptedFakeLLM.invoke should not be used in tests")

    def _stream_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict[str, Any] | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[ModelResponseStream]:
        if self._call_index >= len(self._scripts):
            raise AssertionError(
                f"ScriptedFakeLLM invoked more times than scripted "
                f"({self._call_index} >= {len(self._scripts)})"
            )
        script = self._scripts[self._call_index]
        self._call_index += 1
        self.stream_calls.append(
            {
                "prompt": prompt,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        for chunk in script:
            yield chunk


class ExceptionThrowingLLM(LLM):
    """LLM double that raises an exception mid-stream to test error propagation."""

    def __init__(self, message: str = "LLM stream crashed") -> None:
        self._config = LLMConfig(
            model_provider="fake-provider",
            model_name="raising-llm",
            temperature=0.0,
            max_input_tokens=8192,
        )
        self._message = message

    @property
    def config(self) -> LLMConfig:
        return self._config

    def log_model_configs(self) -> None:
        return None

    def _invoke_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict[str, Any] | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        raise AssertionError("ExceptionThrowingLLM.invoke should not be used in tests")

    def _stream_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict[str, Any] | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[ModelResponseStream]:
        # Emit a first chunk so the stream has already started.
        yield stream_chunk(content="partial response")
        raise RuntimeError(self._message)

    def _invoke_implementation_langchain(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def _stream_implementation_langchain(
        self, *args: Any, **kwargs: Any
    ) -> Iterator[Any]:
        raise NotImplementedError


def stream_chunk(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list[ChatCompletionDeltaToolCall] | None = None,
    finish_reason: str | None = None,
) -> ModelResponseStream:
    return ModelResponseStream(
        id="stream-id",
        created="0",
        choice=StreamingChoice(
            finish_reason=finish_reason,
            delta=Delta(
                content=content,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls or [],
            ),
        ),
    )


def tool_call_chunk(
    *,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
    index: int = 0,
) -> ChatCompletionDeltaToolCall:
    return ChatCompletionDeltaToolCall(
        id=call_id,
        index=index,
        type="function",
        function=FunctionCall(name=name, arguments=arguments),
    )


def configure_llm(
    dependencies: ChatTurnDependencies, scripts: list[list[ModelResponseStream]]
) -> ScriptedFakeLLM:
    llm = ScriptedFakeLLM(scripts)
    dependencies.llm = llm
    return llm


def run_fast_chat_turn(
    sample_messages: list[AgentSDKMessage],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    prompt_config: PromptConfig | None = None,
) -> list[Packet]:
    if prompt_config is None:
        prompt_config = PromptConfig(
            default_behavior_system_prompt="You are a helpful assistant.",
            custom_instructions=None,
            reminder="Answer the user's question.",
            datetime_aware=False,
        )

    generator = fast_chat_turn(
        sample_messages,
        dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
    )
    return list(generator)


def assert_packets_contain_stop(packets: list[Packet]) -> None:
    assert packets, "Expected packets to be emitted"
    assert isinstance(packets[-1].obj, OverallStop), "Last packet should be OverallStop"


def assert_cancellation_packets(
    packets: list[Packet], expect_cancelled_message: bool
) -> None:
    assert len(packets) >= 3
    assert packets[-1].obj.type == "stop"
    assert packets[-2].obj.type == "section_end"
    if expect_cancelled_message:
        assert packets[-3].obj.type == "message_start"
        assert isinstance(packets[-3].obj, MessageStart)
        assert packets[-3].obj.content == "Cancelled"


# =============================================================================
# Pytest fixtures
# =============================================================================


@pytest.fixture
def chat_session_id() -> UUID:
    return uuid4()


@pytest.fixture
def message_id() -> int:
    return 42


@pytest.fixture
def research_type() -> ResearchType:
    return ResearchType.FAST


@pytest.fixture
def sample_messages() -> list[AgentSDKMessage]:
    return [
        SystemMessage(
            role="system",
            content=[
                InputTextContent(
                    type="input_text",
                    text="You are a highly capable assistant",
                )
            ],
        ),
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="hi")],
        ),
    ]


@pytest.fixture
def fake_internal_search_tool_instance() -> FakeTool:
    return FakeTool("internal_search", tool_id=1)


# =============================================================================
# Tests
# =============================================================================


def test_fast_chat_turn_streams_message_packets(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    configure_llm(
        chat_turn_dependencies,
        [
            [
                stream_chunk(reasoning_content="Let me think"),
                stream_chunk(content="Hello"),
                stream_chunk(content=" world"),
                stream_chunk(finish_reason="stop"),
            ]
        ],
    )

    packets = run_fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
    )

    assert_packets_contain_stop(packets)
    content = "".join(
        packet.obj.content or ""
        for packet in packets
        if isinstance(packet.obj, MessageDelta)
    )
    assert content.strip() == "Hello world"


def test_fast_chat_turn_runs_tool_and_follow_up(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    fake_internal_search_tool_instance: FakeTool,
) -> None:
    call_id = "toolu_123"
    first_call = [
        stream_chunk(
            tool_calls=[
                tool_call_chunk(call_id=call_id, name="internal_search", arguments="")
            ]
        ),
        stream_chunk(
            tool_calls=[tool_call_chunk(arguments='{"queries": ["agent migration"]}')]
        ),
        stream_chunk(finish_reason="tool_calls"),
    ]
    second_call = [
        stream_chunk(content="Searched results summary."),
        stream_chunk(finish_reason="stop"),
    ]
    llm = configure_llm(chat_turn_dependencies, [first_call, second_call])
    chat_turn_dependencies.tools = [fake_internal_search_tool_instance]

    packets = run_fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
    )

    assert_packets_contain_stop(packets)
    assert len(llm.stream_calls) == 2
    assert fake_internal_search_tool_instance.calls[0]["queries"] == ["agent migration"]


def test_fast_chat_turn_prompts_include_tool_messages_on_follow_up(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    fake_internal_search_tool_instance: FakeTool,
) -> None:
    call_id = "toolu_prompt"
    first_call = [
        stream_chunk(
            tool_calls=[
                tool_call_chunk(call_id=call_id, name="internal_search", arguments="")
            ]
        ),
        stream_chunk(tool_calls=[tool_call_chunk(arguments='{"queries": ["docs"]}')]),
        stream_chunk(finish_reason="tool_calls"),
    ]
    second_call = [
        stream_chunk(content="Answer with docs"),
        stream_chunk(finish_reason="stop"),
    ]

    llm = configure_llm(chat_turn_dependencies, [first_call, second_call])
    chat_turn_dependencies.tools = [fake_internal_search_tool_instance]

    run_fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
    )

    assert len(llm.stream_calls) == 2
    second_prompt = llm.stream_calls[1]["prompt"]
    assistant_messages = [
        msg for msg in second_prompt if msg.get("role") == "assistant"
    ]
    tool_messages = [msg for msg in second_prompt if msg.get("role") == "tool"]

    assert any("tool_calls" in msg and msg["tool_calls"] for msg in assistant_messages)
    assert any(msg.get("tool_call_id") == call_id for msg in tool_messages)


def test_fast_chat_turn_second_turn_context_handlers(
    chat_turn_dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    llm = configure_llm(
        chat_turn_dependencies,
        [
            [
                stream_chunk(content="Context handled response"),
                stream_chunk(finish_reason="stop"),
            ]
        ],
    )
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Always be polite and helpful.",
        reminder="Answer the user's question.",
        datetime_aware=False,
    )
    starter_messages: list[AgentSDKMessage] = [
        SystemMessage(
            role="system",
            content=[
                InputTextContent(
                    type="input_text",
                    text="You are a helpful assistant.",
                )
            ],
        ),
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="hi")],
        ),
        AssistantMessageWithContent(
            role="assistant",
            content=[InputTextContent(type="input_text", text="I need to use a tool")],
        ),
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="hi again")],
        ),
    ]

    packets = list(
        fast_chat_turn(
            starter_messages,
            chat_turn_dependencies,
            chat_session_id,
            message_id,
            research_type,
            prompt_config,
        )
    )

    assert_packets_contain_stop(packets)
    assert len(llm.stream_calls) == 1
    first_prompt = llm.stream_calls[0]["prompt"]
    assert isinstance(first_prompt, list)
    assert len(first_prompt) == 5
    assert first_prompt[0]["role"] == "system"
    assert first_prompt[1]["role"] == "user"
    assert first_prompt[1]["content"][0]["text"] == "hi"
    assert first_prompt[2]["role"] == "assistant"
    assert first_prompt[2]["content"][0]["text"] == "I need to use a tool"
    assert first_prompt[3]["role"] == "user"
    assert "Custom Instructions" in first_prompt[3]["content"][0]["text"]
    assert first_prompt[4]["role"] == "user"
    assert first_prompt[4]["content"][0]["text"] == "hi again"


def test_fast_chat_turn_context_handlers(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    fake_dummy_tool: Any,
) -> None:
    call_id = "tool-call-context"
    first_call = [
        stream_chunk(
            tool_calls=[
                tool_call_chunk(call_id=call_id, name="dummy_tool", arguments="")
            ]
        ),
        stream_chunk(
            tool_calls=[
                tool_call_chunk(call_id=call_id, arguments="{}"),
            ]
        ),
        stream_chunk(finish_reason="tool_calls"),
    ]
    second_call = [
        stream_chunk(content="Final answer after tool"),
        stream_chunk(finish_reason="stop"),
    ]
    llm = configure_llm(chat_turn_dependencies, [first_call, second_call])
    chat_turn_dependencies.tools = [fake_dummy_tool]
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Always be polite and helpful.",
        reminder="Answer the user's question.",
        datetime_aware=False,
    )

    packets = run_fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
    )

    assert_packets_contain_stop(packets)
    assert len(llm.stream_calls) == 2

    first_prompt = llm.stream_calls[0]["prompt"]
    assert len(first_prompt) == 3
    assert first_prompt[0]["role"] == "system"
    assert first_prompt[1]["role"] == "user"
    assert "Custom Instructions" in first_prompt[1]["content"][0]["text"]
    assert first_prompt[2]["role"] == "user"

    second_prompt = llm.stream_calls[1]["prompt"]
    assert len(second_prompt) == 6
    assert second_prompt[0]["role"] == "system"
    assert second_prompt[1]["role"] == "user"
    assert "Custom Instructions" in second_prompt[1]["content"][0]["text"]
    assert second_prompt[2]["role"] == "user"
    assert second_prompt[3]["type"] == "function_call"
    assert second_prompt[3]["name"] == "dummy_tool"
    assert second_prompt[4]["type"] == "function_call_output"
    assert second_prompt[4]["call_id"] == call_id
    assert second_prompt[5]["role"] == "user"
    assert prompt_config.reminder in second_prompt[5]["content"][0]["text"]


def test_fast_chat_turn_handles_cancellation_before_stream(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    configure_llm(
        chat_turn_dependencies,
        [
            [
                stream_chunk(content="This will not stream"),
                stream_chunk(finish_reason="stop"),
            ]
        ],
    )
    generator = fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
        PromptConfig(
            default_behavior_system_prompt="helper",
            custom_instructions=None,
            reminder="Answer the user's question.",
            datetime_aware=False,
        ),
    )
    set_fence(chat_session_id, chat_turn_dependencies.redis_client, True)
    packets = list(generator)

    assert_cancellation_packets(packets, expect_cancelled_message=True)


def test_fast_chat_turn_handles_cancellation_mid_stream(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    configure_llm(
        chat_turn_dependencies,
        [
            [
                stream_chunk(content="Hello"),
                stream_chunk(content=" world"),
                stream_chunk(finish_reason="stop"),
            ]
        ],
    )
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions=None,
        reminder="Answer the user's question.",
        datetime_aware=False,
    )

    generator = fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
    )

    packets: list[Packet] = []
    cancelled = False
    for packet in generator:
        packets.append(packet)
        if not cancelled and isinstance(packet.obj, MessageDelta):
            set_fence(chat_session_id, chat_turn_dependencies.redis_client, True)
            cancelled = True

    assert cancelled, "Expected to trigger cancellation after receiving a delta packet."
    assert_cancellation_packets(packets, expect_cancelled_message=False)


def test_fast_chat_turn_catch_exception(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    """Ensure exceptions from the agent background thread are surfaced to the caller."""

    chat_turn_dependencies.llm = ExceptionThrowingLLM()

    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions=None,
        reminder="Answer the user's question.",
        datetime_aware=False,
    )

    generator = fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
    )

    with pytest.raises(RuntimeError, match="LLM stream crashed"):
        list(generator)


def test_fast_chat_turn_citation_processing(
    chat_turn_context: ChatTurnContext,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    citation_script = [
        [
            stream_chunk(content="Final answer [[1]](https://example.com/test-doc)"),
            stream_chunk(finish_reason="stop"),
        ]
    ]
    configure_llm(chat_turn_context.run_dependencies, citation_script)

    fake_section = create_test_inference_section()
    fake_iteration = create_test_iteration_answer()

    chat_turn_context.global_iteration_responses = [fake_iteration]
    chat_turn_context.fetched_documents_cache = {
        "test-doc-1": FetchedDocumentCacheEntry(
            inference_section=fake_section,
            document_citation_number=1,
        )
    }
    chat_turn_context.citations = [
        CitationInfo(citation_num=1, document_id="test-doc-1")
    ]

    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions=None,
        reminder="Answer the user's question.",
        datetime_aware=False,
    )

    @unified_event_stream
    def wrapped_fast_chat_turn_core(
        messages: list[AgentSDKMessage],
        dependencies: ChatTurnDependencies,
        session_id: UUID,
        msg_id: int,
        res_type: ResearchType,
        p_config: PromptConfig,
        context: ChatTurnContext,
    ) -> None:
        _fast_chat_turn_core(
            messages,
            dependencies,
            session_id,
            msg_id,
            res_type,
            p_config,
            starter_context=context,
        )

    packets = list(
        wrapped_fast_chat_turn_core(
            sample_messages,
            chat_turn_context.run_dependencies,
            chat_session_id,
            message_id,
            research_type,
            prompt_config,
            chat_turn_context,
        )
    )

    assert_packets_contain_stop(packets)
    assert any(isinstance(packet.obj, CitationStart) for packet in packets)
    assert any(isinstance(packet.obj, CitationDelta) for packet in packets)
