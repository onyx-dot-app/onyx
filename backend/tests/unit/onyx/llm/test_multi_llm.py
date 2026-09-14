import os
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from unittest.mock import ANY, MagicMock, patch

import litellm
import pytest
from litellm.types.utils import ChatCompletionDeltaToolCall, Delta
from litellm.types.utils import Function as LiteLLMFunction
from pydantic import JsonValue

from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.llm.constants import LlmProviderNames
from onyx.llm.exceptions import LLMTimeoutError
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.litellm_models import (
    AssistantMessage,
    LanguageModelInput,
    ModelResponse,
    ModelResponseStream,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from onyx.llm.litellm_models import ToolFunctionCall as FunctionCall
from onyx.llm.model_capabilities import get_max_input_tokens
from onyx.llm.models import NamedToolChoice, ReasoningEffort, ToolChoiceOptions, Usage
from onyx.llm.multi_llm import (
    LitellmTransport,
    _consume_stream_with_timeout,
)

VERTEX_OPUS_MODELS_REJECTING_STREAM_OPTIONS = [
    "claude-opus-4-5@20251101",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
]


def _create_delta(
    role: str | None = None,
    content: str | None = None,
    tool_calls: list[ChatCompletionDeltaToolCall] | None = None,
) -> Delta:
    delta = Delta(role=role, content=content)
    # NOTE: for some reason, if you pass tool_calls to the constructor, it doesn't actually
    # get set, so we have to do it this way
    delta.tool_calls = tool_calls
    return delta


def _model_response_to_assistant_message(response: ModelResponse) -> AssistantMessage:
    """Convert a ModelResponse to an AssistantMessage for testing."""
    message = response.choice.message
    tool_calls = None
    if message.tool_calls:
        tool_calls = [
            ToolCall(
                id=tc.id,
                function=FunctionCall(
                    name=tc.function.name or "",
                    arguments=tc.function.arguments or "",
                ),
            )
            for tc in message.tool_calls
        ]
    return AssistantMessage(
        content=message.content,
        tool_calls=tool_calls,
    )


def _accumulate_stream_to_assistant_message(
    stream_chunks: list[ModelResponseStream],
) -> AssistantMessage:
    """Accumulate streaming deltas into a final AssistantMessage for testing."""
    accumulated_content = ""
    tool_calls_map: dict[int, dict[str, str]] = {}

    for chunk in stream_chunks:
        delta = chunk.choice.delta

        # Accumulate content
        if delta.content:
            accumulated_content += delta.content

        # Accumulate tool calls
        if delta.tool_calls:
            for tool_call_delta in delta.tool_calls:
                index = tool_call_delta.index

                if index not in tool_calls_map:
                    tool_calls_map[index] = {
                        "id": "",
                        "name": "",
                        "arguments": "",
                    }

                if tool_call_delta.id:
                    tool_calls_map[index]["id"] = tool_call_delta.id

                if tool_call_delta.function:
                    if tool_call_delta.function.name:
                        tool_calls_map[index]["name"] = tool_call_delta.function.name
                    if tool_call_delta.function.arguments:
                        tool_calls_map[index]["arguments"] += (
                            tool_call_delta.function.arguments
                        )

    # Convert accumulated tool calls to ToolCall list, sorted by index
    tool_calls = None
    if tool_calls_map:
        tool_calls = [
            ToolCall(
                type="function",
                id=tc_data["id"],
                function=FunctionCall(
                    name=tc_data["name"],
                    arguments=tc_data["arguments"],
                ),
            )
            for index in sorted(tool_calls_map.keys())
            for tc_data in [tool_calls_map[index]]
            if tc_data["id"] and tc_data["name"]
        ]

    return AssistantMessage(
        content=accumulated_content if accumulated_content else None,
        tool_calls=tool_calls,
    )


@pytest.fixture
def default_multi_llm() -> LitellmTransport:
    model_provider = LlmProviderNames.OPENAI
    model_name = "gpt-3.5-turbo"

    return LitellmTransport(
        api_key="test_key",
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
    )


def test_multiple_tool_calls(default_multi_llm: LitellmTransport) -> None:
    # Mock the litellm.completion function
    with patch("litellm.completion") as mock_completion:
        # Env injection defaults on outside multi-tenant, and this test does not
        # patch it, so invoke() takes the streamed transport and the mock must
        # return stream chunks. Plain-transport tool calls are covered by
        # test_model_response_choice_merge.py.
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(
                            tool_calls=[
                                ChatCompletionDeltaToolCall(
                                    id="call_1",
                                    function=LiteLLMFunction(
                                        name="get_weather",
                                        arguments='{"location": "New York"}',
                                    ),
                                    type="function",
                                    index=0,
                                ),
                                ChatCompletionDeltaToolCall(
                                    id="call_2",
                                    function=LiteLLMFunction(
                                        name="get_time",
                                        arguments='{"timezone": "EST"}',
                                    ),
                                    type="function",
                                    index=1,
                                ),
                            ],
                        ),
                        finish_reason="tool_calls",
                        index=0,
                    )
                ],
                model="gpt-3.5-turbo",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        # Define input messages
        messages: LanguageModelInput = [
            UserMessage(content="What's the weather and time in New York?")
        ]

        # Define available tools
        tools: list[dict[str, JsonValue]] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get the current time for a timezone",
                    "parameters": {
                        "type": "object",
                        "properties": {"timezone": {"type": "string"}},
                        "required": ["timezone"],
                    },
                },
            },
        ]

        result = default_multi_llm.invoke(messages, tools)

        # Assert that the result is a ModelResponse
        assert isinstance(result, ModelResponse)

        # Convert to AssistantMessage for easier assertion
        assistant_msg = _model_response_to_assistant_message(result)

        # Assert that the content is None (as per the mock response)
        assert assistant_msg.content is None or assistant_msg.content == ""

        # Assert that there are two tool calls
        assert assistant_msg.tool_calls is not None
        assert len(assistant_msg.tool_calls) == 2

        # Assert the details of the first tool call
        assert assistant_msg.tool_calls[0].id == "call_1"
        assert assistant_msg.tool_calls[0].function.name == "get_weather"
        assert (
            assistant_msg.tool_calls[0].function.arguments == '{"location": "New York"}'
        )

        # Assert the details of the second tool call
        assert assistant_msg.tool_calls[1].id == "call_2"
        assert assistant_msg.tool_calls[1].function.name == "get_time"
        assert assistant_msg.tool_calls[1].function.arguments == '{"timezone": "EST"}'

        # Verify that litellm.completion was called with the correct arguments
        mock_completion.assert_called_once_with(
            model="openai/responses/gpt-3.5-turbo",
            api_key="test_key",
            base_url=None,
            api_version=None,
            custom_llm_provider=None,
            messages=[
                {"role": "user", "content": "What's the weather and time in New York?"}
            ],
            tools=tools,
            stream=True,
            temperature=0.0,  # Default value from GEN_AI_TEMPERATURE
            # The time left of the 60s default, just under 60 when sent.
            timeout=pytest.approx(60, abs=1),
            max_tokens=None,
            client=ANY,  # HTTPHandler instance created per-request
            stream_options={"include_usage": True},
            parallel_tool_calls=True,
            mock_response=MOCK_LLM_RESPONSE,
            allowed_openai_params=["tool_choice"],
        )


def test_multiple_tool_calls_streaming(default_multi_llm: LitellmTransport) -> None:
    # Mock the litellm.completion function
    with patch("litellm.completion") as mock_completion:
        # Create a mock response with multiple tool calls using litellm objects
        mock_response = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(
                            tool_calls=[
                                ChatCompletionDeltaToolCall(
                                    id="call_1",
                                    function=LiteLLMFunction(
                                        name="get_weather", arguments='{"location": '
                                    ),
                                    type="function",
                                    index=0,
                                )
                            ],
                        ),
                        finish_reason=None,
                        index=0,
                    )
                ],
                model="gpt-3.5-turbo",
            ),
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(
                            tool_calls=[
                                ChatCompletionDeltaToolCall(
                                    id="",
                                    function=LiteLLMFunction(arguments='"New York"}'),
                                    type="function",
                                    index=0,
                                )
                            ]
                        ),
                        finish_reason=None,
                        index=0,
                    )
                ],
                model="gpt-3.5-turbo",
            ),
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(
                            tool_calls=[
                                ChatCompletionDeltaToolCall(
                                    id="call_2",
                                    function=LiteLLMFunction(
                                        name="get_time", arguments='{"timezone": "EST"}'
                                    ),
                                    type="function",
                                    index=1,
                                )
                            ]
                        ),
                        finish_reason="tool_calls",
                        index=0,
                    )
                ],
                model="gpt-3.5-turbo",
            ),
        ]
        mock_completion.return_value = mock_response

        # Define input messages and tools (same as in the non-streaming test)
        messages: LanguageModelInput = [
            UserMessage(content="What's the weather and time in New York?")
        ]

        tools: list[dict[str, JsonValue]] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get the current time for a timezone",
                    "parameters": {
                        "type": "object",
                        "properties": {"timezone": {"type": "string"}},
                        "required": ["timezone"],
                    },
                },
            },
        ]

        # Call the stream method
        stream_result = list(default_multi_llm.stream(messages, tools))

        # Assert that we received the correct number of chunks
        assert len(stream_result) == 3

        # Assert that each chunk is a ModelResponseStream
        for chunk in stream_result:
            assert isinstance(chunk, ModelResponseStream)

        # Accumulate the stream chunks into a final AssistantMessage
        final_result = _accumulate_stream_to_assistant_message(stream_result)

        # Assert that the final result matches our expectations
        assert isinstance(final_result, AssistantMessage)
        assert final_result.content is None or final_result.content == ""
        assert final_result.tool_calls is not None
        assert len(final_result.tool_calls) == 2
        assert final_result.tool_calls[0].id == "call_1"
        assert final_result.tool_calls[0].function.name == "get_weather"
        assert (
            final_result.tool_calls[0].function.arguments == '{"location": "New York"}'
        )
        assert final_result.tool_calls[1].id == "call_2"
        assert final_result.tool_calls[1].function.name == "get_time"
        assert final_result.tool_calls[1].function.arguments == '{"timezone": "EST"}'

        # Verify that litellm.completion was called with the correct arguments
        mock_completion.assert_called_once_with(
            model="openai/responses/gpt-3.5-turbo",
            api_key="test_key",
            base_url=None,
            api_version=None,
            custom_llm_provider=None,
            messages=[
                {"role": "user", "content": "What's the weather and time in New York?"}
            ],
            tools=tools,
            stream=True,
            temperature=0.0,  # Default value from GEN_AI_TEMPERATURE
            # The time left of the 60s default, just under 60 when sent.
            timeout=pytest.approx(60, abs=1),
            max_tokens=None,
            client=ANY,  # HTTPHandler instance created per-stream
            stream_options={"include_usage": True},
            parallel_tool_calls=True,
            mock_response=MOCK_LLM_RESPONSE,
            allowed_openai_params=["tool_choice"],
        )


ANTHROPIC_MODELS_OMITTING_SAMPLING_PARAMS = [
    "claude-opus-4-7",
    "claude-opus-4-7@20260101",
    "claude-opus-4.7",
    "claude-4-7-opus",
    "claude-4.7-opus",
    "claude-opus-4-8",
    "claude-opus-4-8@20260101",
    "claude-opus-4.8",
    "claude-4-8-opus",
    "claude-4.8-opus",
    "claude-fable-5",
    "claude-fable-5@20260101",
    "claude-5-fable",
    "claude-mythos-5",
    "claude-5-mythos",
    "claude-sonnet-5",
    "claude-sonnet-5@20260203",
    "claude-5-sonnet",
    "claude-opus-5",
    "claude-opus-5@20260101",
    "claude-5-opus",
]


@pytest.mark.parametrize("model_name", ANTHROPIC_MODELS_OMITTING_SAMPLING_PARAMS)
def test_omits_temperature_for_no_sampling_params_models(model_name: str) -> None:
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.LITELLM_PROXY,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.LITELLM_PROXY,
            model_name=model_name,
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))

        kwargs = mock_completion.call_args.kwargs
        assert "temperature" not in kwargs


def test_empty_tools_list_is_omitted(default_multi_llm: LitellmTransport) -> None:
    # Some OpenAI-compatible servers reject requests carrying `tools: []`;
    # an empty list must be dropped from the request entirely.
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(default_multi_llm.stream(messages, tools=[]))

        assert mock_completion.call_args.kwargs["tools"] is None


def test_claude_only_in_deployment_name_omits_temperature_and_reasons() -> None:
    # Custom providers (e.g. Azure AI Foundry) may carry the model identity only
    # in the deployment alias — the string actually sent to LiteLLM — while
    # model_name is an opaque label. Detection must consider both, including for
    # the reasoning path: model_is_reasoning_model is deliberately NOT patched
    # here, since the litellm registry can't know the opaque alias — adaptive
    # thinking must be inferred from the Claude version alone.
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.LITELLM_PROXY,
        model_name="foundry-deploy-1",
        deployment_name="claude-opus-5",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.LITELLM_PROXY,
            model_name="foundry-deploy-1",
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.HIGH))

        kwargs = mock_completion.call_args.kwargs
        assert "temperature" not in kwargs
        assert kwargs["thinking"] == {"type": "adaptive"}
        assert kwargs["output_config"] == {"effort": "high"}


def test_openai_only_in_deployment_name_uses_responses_bridge() -> None:
    # is_openai_model must also check deployment_name: an Azure Foundry model
    # identified only by its alias must still route through the responses
    # bridge (and get the api-version override), not the plain chat surface.
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.AZURE,
        model_name="foundry-deploy-4",
        deployment_name="gpt-5.1",
        api_base="https://my-resource.openai.azure.us",
        api_version="2025-03-01-preview",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.AZURE,
            model_name="foundry-deploy-4",
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.HIGH))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["model"] == "azure/responses/gpt-5.1"
        assert kwargs["api_version"] is None
        assert kwargs["reasoning"]["effort"] == "high"


@pytest.mark.parametrize(
    "model_name",
    [
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-fable-5",
        "claude-5-fable",
        "claude-mythos-5",
        "claude-5-mythos",
        "claude-sonnet-5",
        "claude-5-sonnet",
        "claude-opus-5",
        "claude-5-opus",
    ],
)
@pytest.mark.parametrize(
    "reasoning_effort, expected_effort",
    [
        (ReasoningEffort.AUTO, "medium"),
        (ReasoningEffort.LOW, "low"),
        (ReasoningEffort.HIGH, "high"),
    ],
)
def test_claude_adaptive_thinking_uses_output_config(
    model_name: str, reasoning_effort: ReasoningEffort, expected_effort: str
) -> None:
    # Non-Vertex providers must use the adaptive thinking API for these models
    # (thinking.type=adaptive + output_config.effort) rather than the legacy
    # thinking.type.enabled + budget_tokens path, which they reject with a 400.
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.LITELLM_PROXY,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.LITELLM_PROXY,
            model_name=model_name,
        ),
    )

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=True),
    ):
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=reasoning_effort))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["thinking"] == {"type": "adaptive"}
        assert kwargs["output_config"] == {"effort": expected_effort}
        assert "budget_tokens" not in kwargs["thinking"]


def test_keeps_temperature_for_other_models(
    default_multi_llm: LitellmTransport,
) -> None:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(default_multi_llm.stream(messages))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["temperature"] == 0.0


@pytest.mark.parametrize(
    "model_name",
    [
        "claude-sonnet-4-5",
        "claude-sonnet-4-6",
        "claude-3-5-sonnet-20241022",
    ],
)
def test_keeps_temperature_for_older_sonnet_models(model_name: str) -> None:
    # The no-sampling-params match is substring-based; make sure sonnet-5
    # entries don't catch older sonnets, which still accept temperature.
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.LITELLM_PROXY,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.LITELLM_PROXY,
            model_name=model_name,
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))

        kwargs = mock_completion.call_args.kwargs
        assert "temperature" in kwargs


@pytest.mark.parametrize("model_name", VERTEX_OPUS_MODELS_REJECTING_STREAM_OPTIONS)
def test_vertex_stream_omits_stream_options(model_name: str) -> None:
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.VERTEX_AI,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.VERTEX_AI,
            model_name=model_name,
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))

        kwargs = mock_completion.call_args.kwargs
        assert "stream_options" not in kwargs


def test_openai_auto_reasoning_effort_maps_to_medium() -> None:
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.OPENAI,
        model_name="gpt-5.2",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.OPENAI,
            model_name="gpt-5.2",
        ),
    )

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=True),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=True),
    ):
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.AUTO))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["reasoning"]["effort"] == "medium"


@pytest.mark.parametrize("model_name", VERTEX_OPUS_MODELS_REJECTING_STREAM_OPTIONS)
def test_vertex_opus_still_sends_thinking(model_name: str) -> None:
    """Rejecting stream_options must not cost these models their reasoning:
    thinking is still sent."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.VERTEX_AI,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.VERTEX_AI,
            model_name=model_name,
        ),
    )

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=True),
    ):
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.HIGH))

        kwargs = mock_completion.call_args.kwargs
        assert "thinking" in kwargs


def test_claude_via_openai_compatible_proxy_uses_reasoning_param() -> None:
    """The wire format follows the API surface, not the model vendor: Claude
    behind an OpenAI-shaped gateway asks for reasoning the OpenAI way, never
    Anthropic's thinking/output_config."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.BIFROST,
        model_name="anthropic/claude-sonnet-4-5",
        api_base="https://gateway.example/v1",
        max_input_tokens=200000,
        custom_config={"bifrost_api_mode": "chat_completions"},
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.HIGH))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["reasoning"] == {"effort": "high", "summary": "auto"}
        assert "thinking" not in kwargs
        assert "output_config" not in kwargs


@pytest.mark.parametrize("api_mode", ["chat_completions", "responses"])
def test_openai_via_openai_compatible_proxy_reaches_xhigh(api_mode: str) -> None:
    """An OpenAI model behind a gateway is still an OpenAI model: it takes the
    OpenAI reasoning param, and xhigh reaches it instead of being clamped to
    high by the LiteLLM fallback."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.BIFROST,
        model_name="openai/gpt-5.1",
        api_base="https://gateway.example/v1",
        max_input_tokens=200000,
        custom_config={"bifrost_api_mode": api_mode},
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.XHIGH))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["reasoning"] == {"effort": "xhigh", "summary": "auto"}
        assert "reasoning_effort" not in kwargs


def test_gateway_chat_alias_only_silences_openai_models() -> None:
    """The "-chat" rule is an OpenAI quirk (their chat models reject reasoning
    params). A Claude alias that happens to contain it must still reason."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.BIFROST,
        model_name="anthropic/claude-sonnet-4-5-chat",
        api_base="https://gateway.example/v1",
        max_input_tokens=200000,
        custom_config={"bifrost_api_mode": "chat_completions"},
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.HIGH))

        assert mock_completion.call_args.kwargs["reasoning"] == {
            "effort": "high",
            "summary": "auto",
        }


def test_aliased_claude_model_still_reasons() -> None:
    """A gateway alias the litellm registry doesn't know still reasons: the
    version parsed off the name decides, not the registry."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.VERTEX_AI,
        model_name="gateway-claude-sonnet-4-5-prod",
        max_input_tokens=100000,
    )

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=False),
    ):
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.HIGH))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 4096}


@pytest.mark.parametrize(
    "max_tokens, expected_thinking",
    [
        (None, {"type": "enabled", "budget_tokens": 4096}),
        (8000, {"type": "enabled", "budget_tokens": 4096}),
        (5000, {"type": "enabled", "budget_tokens": 3976}),
        (2048, {"type": "enabled", "budget_tokens": 1024}),
        (2000, None),
    ],
)
def test_legacy_claude_thinking_budget_fits_inside_max_tokens(
    max_tokens: int | None,
    expected_thinking: dict[str, int | str] | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.llm.multi_llm.GEN_AI_NUM_RESERVED_OUTPUT_TOKENS", 1024)
    llm = LitellmLLM(
        api_key="test_key",
        model_provider=LlmProviderNames.VERTEX_AI,
        model_name="claude-sonnet-4-5",
        max_input_tokens=100000,
    )

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=False),
        patch("onyx.llm.multi_llm.logger.warning") as warning,
    ):
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(
            llm.stream(
                messages, reasoning_effort=ReasoningEffort.HIGH, max_tokens=max_tokens
            )
        )

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["max_tokens"] == max_tokens
        if expected_thinking is None:
            assert "thinking" not in kwargs
            warning.assert_called_once()
            assert "Skipping Anthropic thinking" in warning.call_args.args[0]
            assert warning.call_args.args[1] == max_tokens
        else:
            assert kwargs["thinking"] == expected_thinking
            warning.assert_not_called()


def test_openai_chat_omits_reasoning_params() -> None:
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.OPENAI,
        model_name="gpt-5-chat",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.OPENAI,
            model_name="gpt-5-chat",
        ),
    )

    with (
        patch("litellm.completion") as mock_completion,
        patch(
            "onyx.llm.multi_llm.model_is_reasoning_model", return_value=True
        ) as mock_is_reasoning,
        patch(
            "onyx.llm.multi_llm.is_true_openai_model", return_value=True
        ) as mock_is_openai,
    ):
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(content="Hello"),
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="gpt-5-chat",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        llm.invoke(messages)

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["model"] == "openai/responses/gpt-5-chat"
        assert "reasoning" not in kwargs
        assert "reasoning_effort" not in kwargs
        assert mock_is_reasoning.called
        assert mock_is_openai.called


def test_chat_variant_only_in_deployment_name_omits_reasoning() -> None:
    """The "-chat" guard reads the wire string (deployment_name takes
    priority), so a real gpt-5-chat model hidden behind an opaque alias
    must still have reasoning omitted or OpenAI 400s it."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.AZURE,
        model_name="gpt-5-chat",
        deployment_name="prod-deploy-1",
        api_base="https://my-resource.openai.azure.us",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.AZURE, model_name="gpt-5-chat"
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.HIGH))

        kwargs = mock_completion.call_args.kwargs
        assert "reasoning" not in kwargs


def test_coincidental_chat_alias_does_not_silence_reasoning() -> None:
    """A deployment alias merely containing "-chat" (not a real gpt-5-chat
    registry model) must not silently suppress reasoning for a model that
    otherwise supports it."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.AZURE,
        model_name="gpt-5.1",
        deployment_name="prod-chat-1",
        api_base="https://my-resource.openai.azure.us",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.AZURE, model_name="gpt-5.1"
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.HIGH))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["reasoning"]["effort"] == "high"


def _azure_llm(model_name: str, api_version: str | None) -> LitellmTransport:
    return LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.AZURE,
        model_name=model_name,
        api_base="https://my-resource.openai.azure.us",
        api_version=api_version,
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.AZURE,
            model_name=model_name,
        ),
    )


def _stream_and_get_completion_kwargs(
    llm: LitellmTransport, is_openai: bool
) -> dict[str, Any]:
    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=is_openai),
    ):
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))
        return dict(mock_completion.call_args.kwargs)


@pytest.mark.parametrize(
    "configured_api_version", ["2025-03-01-preview", "2024-08-01-preview"]
)
def test_azure_responses_bridge_drops_dated_api_version(
    configured_api_version: str,
) -> None:
    """Responses-bridge calls must target the v1 surface: a dated api-version
    makes LiteLLM build the legacy /openai/responses URL, which sovereign
    clouds (e.g. Azure Government) do not serve (#11420). Dropping it defers
    to LiteLLM's responses default (AZURE_DEFAULT_RESPONSES_API_VERSION)."""
    llm = _azure_llm("gpt-5.1", api_version=configured_api_version)
    kwargs = _stream_and_get_completion_kwargs(llm, is_openai=True)
    assert kwargs["model"] == "azure/responses/gpt-5.1"
    assert kwargs["api_version"] is None


@pytest.mark.parametrize("configured_api_version", ["preview", "latest", "v1"])
def test_azure_responses_bridge_keeps_v1_api_version(
    configured_api_version: str,
) -> None:
    llm = _azure_llm("gpt-5.1", api_version=configured_api_version)
    kwargs = _stream_and_get_completion_kwargs(llm, is_openai=True)
    assert kwargs["api_version"] == configured_api_version


def test_azure_responses_bridge_leaves_none_api_version() -> None:
    """None must stay None so LiteLLM's AZURE_DEFAULT_RESPONSES_API_VERSION
    env override keeps working."""
    llm = _azure_llm("gpt-5.1", api_version=None)
    kwargs = _stream_and_get_completion_kwargs(llm, is_openai=True)
    assert kwargs["api_version"] is None


def test_azure_chat_completions_keeps_dated_api_version() -> None:
    """Non-bridge Azure calls keep the admin-configured dated api-version."""
    llm = _azure_llm("mistral-large", api_version="2025-03-01-preview")
    kwargs = _stream_and_get_completion_kwargs(llm, is_openai=False)
    assert kwargs["model"] == "azure/mistral-large"
    assert kwargs["api_version"] == "2025-03-01-preview"


def test_non_azure_responses_bridge_keeps_api_version() -> None:
    """The upgrade is Azure-only: a LiteLLM proxy fronting Azure manages its
    own upstream routing, so its configured api-version passes through."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.LITELLM_PROXY,
        model_name="gpt-5.1",
        api_base="https://my-proxy.internal",
        api_version="2025-03-01-preview",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.LITELLM_PROXY,
            model_name="gpt-5.1",
        ),
    )
    kwargs = _stream_and_get_completion_kwargs(llm, is_openai=True)
    assert kwargs["model"] == "litellm_proxy/responses/gpt-5.1"
    assert kwargs["api_version"] == "2025-03-01-preview"


@pytest.mark.parametrize("model_name", ["o1-mini", "o1-preview", "o1-mini-2024-09-12"])
@pytest.mark.parametrize("routed_via_responses", [True, False])
def test_reasoning_effort_omitted_for_models_rejecting_it(
    model_name: str, routed_via_responses: bool
) -> None:
    """o1-mini / o1-preview reject the reasoning-effort parameter on every API
    surface; neither the nested responses param nor the root-level one may be
    sent, regardless of routing."""
    llm = _azure_llm(model_name, api_version="2025-03-01-preview")

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=True),
        patch(
            "onyx.llm.multi_llm.is_true_openai_model",
            return_value=routed_via_responses,
        ),
    ):
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.AUTO))

        kwargs = mock_completion.call_args.kwargs
        assert "reasoning" not in kwargs
        assert "reasoning_effort" not in kwargs


def test_reasoning_effort_sent_for_o1() -> None:
    """The o1-mini/o1-preview deny-list must not catch the bare o1 model."""
    llm = _azure_llm("o1", api_version="2025-03-01-preview")

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=True),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=True),
    ):
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.AUTO))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["reasoning"]["effort"] == "medium"


def test_o1_mini_only_in_deployment_name_omits_reasoning_effort() -> None:
    """The o1-mini/o1-preview rejection guard is name-only by design and must
    consider the deployment alias too, not just model_name. Same identity
    gap as test_claude_only_in_deployment_name_omits_temperature_and_reasons."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.AZURE,
        model_name="foundry-deploy-2",
        deployment_name="o1-mini",
        api_base="https://my-resource.openai.azure.us",
        api_version="2025-03-01-preview",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.AZURE,
            model_name="foundry-deploy-2",
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages, reasoning_effort=ReasoningEffort.AUTO))

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["temperature"] == 1  # confirms is_reasoning resolved True
        assert "reasoning" not in kwargs
        assert "reasoning_effort" not in kwargs


def test_user_identity_metadata_enabled(default_multi_llm: LitellmTransport) -> None:
    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.utils.SEND_USER_METADATA_TO_LLM_PROVIDER", True),
    ):
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(content="Hello"),
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="gpt-3.5-turbo",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        identity = LLMUserIdentity(user_id="user_123", session_id="session_abc")

        default_multi_llm.invoke(messages, user_identity=identity)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert kwargs["user"] == "user_123"
        assert kwargs["metadata"]["session_id"] == "session_abc"


def test_user_identity_user_id_truncated_to_64_chars(
    default_multi_llm: LitellmTransport,
) -> None:
    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.utils.SEND_USER_METADATA_TO_LLM_PROVIDER", True),
    ):
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(content="Hello"),
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="gpt-3.5-turbo",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        long_user_id = "u" * 82
        identity = LLMUserIdentity(user_id=long_user_id, session_id="session_abc")

        default_multi_llm.invoke(messages, user_identity=identity)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert kwargs["user"] == long_user_id[:64]


def test_user_identity_metadata_disabled_omits_identity(
    default_multi_llm: LitellmTransport,
) -> None:
    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.utils.SEND_USER_METADATA_TO_LLM_PROVIDER", False),
    ):
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(content="Hello"),
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="gpt-3.5-turbo",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        identity = LLMUserIdentity(user_id="user_123", session_id="session_abc")

        default_multi_llm.invoke(messages, user_identity=identity)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert "user" not in kwargs
        assert "metadata" not in kwargs


def test_existing_metadata_pass_through_when_identity_disabled() -> None:
    model_provider = LlmProviderNames.OPENAI
    model_name = "gpt-3.5-turbo"

    llm = LitellmTransport(
        api_key="test_key",
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
        model_kwargs={"metadata": {"foo": "bar"}},
    )

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.utils.SEND_USER_METADATA_TO_LLM_PROVIDER", False),
    ):
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(content="Hello"),
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="gpt-3.5-turbo",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        identity = LLMUserIdentity(user_id="user_123", session_id="session_abc")

        llm.invoke(messages, user_identity=identity)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert "user" not in kwargs
        assert kwargs["metadata"]["foo"] == "bar"


def test_openai_model_invoke_uses_httphandler_client(
    default_multi_llm: LitellmTransport,
) -> None:
    """Test that OpenAI models get an HTTPHandler client passed for invoke()."""
    from litellm import HTTPHandler

    with patch("litellm.completion") as mock_completion:
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(content="Hello"),
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="gpt-3.5-turbo",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        default_multi_llm.invoke(messages)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert isinstance(kwargs["client"], HTTPHandler)


def test_openai_model_stream_uses_httphandler_client(
    default_multi_llm: LitellmTransport,
) -> None:
    """Test that OpenAI models get an HTTPHandler client passed for stream()."""
    from litellm import HTTPHandler

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(default_multi_llm.stream(messages))

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert isinstance(kwargs["client"], HTTPHandler)


def test_anthropic_model_passes_isolated_client() -> None:
    """Anthropic gets a per-call HTTPHandler so abandoned streams can't deadlock
    litellm's shared module_level_client pool (see _uses_isolated_client)."""
    from litellm import HTTPHandler

    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.ANTHROPIC,
        model_name="claude-3-opus-20240229",
        max_input_tokens=200000,
    )

    with patch("litellm.completion") as mock_completion:
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(content="Hello"),
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="claude-3-opus-20240229",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        llm.invoke(messages)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert isinstance(kwargs["client"], HTTPHandler)


@pytest.mark.parametrize(
    "model_provider",
    [LlmProviderNames.BEDROCK, LlmProviderNames.BEDROCK_CONVERSE],
)
def test_bedrock_model_passes_isolated_client(model_provider: str) -> None:
    """Bedrock gets a per-call HTTPHandler so abandoned streams can't deadlock
    litellm's shared module_level_client pool (see _uses_isolated_client)."""
    from litellm import HTTPHandler

    llm = LitellmTransport(
        api_key=None,
        model_provider=model_provider,
        model_name="anthropic.claude-3-sonnet-20240229-v1:0",
        max_input_tokens=200000,
    )

    with patch("litellm.completion") as mock_completion:
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(content="Hello"),
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="anthropic.claude-3-sonnet-20240229-v1:0",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        llm.invoke(messages)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert isinstance(kwargs["client"], HTTPHandler)


def test_azure_openai_model_uses_httphandler_client() -> None:
    """Test that Azure OpenAI models get an HTTPHandler client passed.

    Azure OpenAI uses the same responses API as OpenAI, so it needs
    the same HTTPHandler isolation to avoid connection pool conflicts.
    """
    from litellm import HTTPHandler

    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.AZURE,
        model_name="gpt-4o",
        api_base="https://my-resource.openai.azure.com",
        api_version="2024-02-15-preview",
        max_input_tokens=128000,
    )

    with patch("litellm.completion") as mock_completion:
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(content="Hello"),
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="gpt-4o",
            ),
        ]
        mock_completion.return_value = mock_stream_chunks

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        llm.invoke(messages)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert isinstance(kwargs["client"], HTTPHandler)


def test_openai_only_in_deployment_name_gets_isolated_client() -> None:
    """_uses_isolated_client() must also check deployment_name: an Azure
    Foundry model identified solely by its alias still needs the per-call
    HTTPHandler, or it silently rejoins litellm's shared connection pool."""
    from litellm import HTTPHandler

    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.AZURE,
        model_name="foundry-deploy-5",
        deployment_name="gpt-5.1",
        api_base="https://my-resource.openai.azure.us",
        api_version="2025-03-01-preview",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.AZURE,
            model_name="foundry-deploy-5",
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert isinstance(kwargs["client"], HTTPHandler)


def test_invokes_without_custom_config_run_concurrently() -> None:
    """Independent provider calls can establish connections concurrently."""
    model_provider = LlmProviderNames.OPENAI
    model_name = "gpt-3.5-turbo"

    def build_llm(api_key: str) -> LitellmTransport:
        return LitellmTransport(
            api_key=api_key,
            model_provider=model_provider,
            model_name=model_name,
            max_input_tokens=get_max_input_tokens(
                model_provider=model_provider,
                model_name=model_name,
            ),
        )

    llm_a = build_llm("key_a")
    llm_b = build_llm("key_b")

    mock_stream_chunks = [
        litellm.ModelResponse(
            id="chatcmpl-123",
            choices=[
                litellm.Choices(
                    delta=_create_delta(content="Hi"),
                    finish_reason="stop",
                    index=0,
                )
            ],
            model=model_name,
        ),
    ]

    a_inside = threading.Event()
    b_inside = threading.Event()

    def fake_completion(**kwargs: Any) -> list[litellm.ModelResponse]:
        # Both connections must start before either response completes.
        api_key = kwargs.get("api_key", "")
        mine, other = (
            (a_inside, b_inside) if api_key == "key_a" else (b_inside, a_inside)
        )
        mine.set()
        assert other.wait(timeout=5), "Independent provider calls were serialized"
        return mock_stream_chunks

    errors: list[Exception] = []

    def run_llm(llm: LitellmTransport) -> None:
        try:
            llm.invoke([UserMessage(content="Hi")])
        except Exception as e:
            errors.append(e)

    with patch("litellm.completion", side_effect=fake_completion):
        t_a = threading.Thread(target=run_llm, args=(llm_a,))
        t_b = threading.Thread(target=run_llm, args=(llm_b,))

        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

    assert not errors, f"Thread errors: {errors}"
    assert a_inside.is_set() and b_inside.is_set()


def test_messages_contain_tool_content_with_tool_role() -> None:
    from onyx.llm.multi_llm import _messages_contain_tool_content

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "I'll search for that."},
        {"role": "tool", "content": "search results", "tool_call_id": "tc_1"},
    ]
    assert _messages_contain_tool_content(messages) is True


def test_messages_contain_tool_content_with_tool_calls() -> None:
    from onyx.llm.multi_llm import _messages_contain_tool_content

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Hello"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tc_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
        },
    ]
    assert _messages_contain_tool_content(messages) is True


def test_messages_contain_tool_content_without_tools() -> None:
    from onyx.llm.multi_llm import _messages_contain_tool_content

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    assert _messages_contain_tool_content(messages) is False


def test_strip_tool_content_converts_assistant_tool_calls_to_text() -> None:
    from onyx.llm.multi_llm import _strip_tool_content_from_messages

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Search for cats"},
        {
            "role": "assistant",
            "content": "Let me search.",
            "tool_calls": [
                {
                    "id": "tc_1",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": '{"query": "cats"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": "Found 3 results about cats.",
            "tool_call_id": "tc_1",
        },
        {"role": "assistant", "content": "Here are the results."},
    ]

    result = _strip_tool_content_from_messages(messages)

    assert len(result) == 4

    # First message unchanged
    assert result[0] == {"role": "user", "content": "Search for cats"}

    # Assistant with tool calls → plain text
    assert result[1]["role"] == "assistant"
    assert "tool_calls" not in result[1]
    assert isinstance(result[1]["content"], str)
    assert "Let me search." in result[1]["content"]
    assert "[Tool Call]" in result[1]["content"]
    assert "search" in result[1]["content"]
    assert "tc_1" in result[1]["content"]

    # Tool response → user message
    assert result[2]["role"] == "user"
    assert isinstance(result[2]["content"], str)
    assert "[Tool Result]" in result[2]["content"]
    assert "tc_1" in result[2]["content"]
    assert "Found 3 results about cats." in result[2]["content"]

    # Final assistant message unchanged
    assert result[3] == {"role": "assistant", "content": "Here are the results."}


def test_strip_tool_content_handles_assistant_with_no_text_content() -> None:
    from onyx.llm.multi_llm import _strip_tool_content_from_messages

    messages: list[dict[str, Any]] = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tc_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
        },
    ]

    result = _strip_tool_content_from_messages(messages)
    assert result[0]["role"] == "assistant"
    assert isinstance(result[0]["content"], str)
    assert "[Tool Call]" in result[0]["content"]
    assert "tool_calls" not in result[0]


def test_strip_tool_content_passes_through_non_tool_messages() -> None:
    from onyx.llm.multi_llm import _strip_tool_content_from_messages

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
    ]

    result = _strip_tool_content_from_messages(messages)
    assert result == messages


def test_strip_tool_content_handles_list_content_blocks() -> None:
    from onyx.llm.multi_llm import _strip_tool_content_from_messages

    messages: list[dict[str, Any]] = [
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Searching now."}],
            "tool_calls": [
                {
                    "id": "tc_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "content": [
                {"type": "text", "text": "result A"},
                {"type": "text", "text": "result B"},
            ],
            "tool_call_id": "tc_1",
        },
    ]

    result = _strip_tool_content_from_messages(messages)

    # Assistant: list content flattened + tool call appended
    assert result[0]["role"] == "assistant"
    assert isinstance(result[0]["content"], str)
    assert "Searching now." in result[0]["content"]
    assert "[Tool Call]" in result[0]["content"]
    assert isinstance(result[0]["content"], str)

    # Tool: list content flattened into user message
    assert result[1]["role"] == "user"
    assert isinstance(result[1]["content"], str)
    assert "result A" in result[1]["content"]
    assert "result B" in result[1]["content"]
    assert isinstance(result[1]["content"], str)


def test_strip_tool_content_merges_consecutive_tool_results() -> None:
    """Bedrock requires strict user/assistant alternation. Multiple parallel
    tool results must be merged into a single user message."""
    from onyx.llm.multi_llm import _strip_tool_content_from_messages

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "weather and news?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tc_1",
                    "type": "function",
                    "function": {"name": "search_weather", "arguments": "{}"},
                },
                {
                    "id": "tc_2",
                    "type": "function",
                    "function": {"name": "search_news", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "content": "sunny 72F", "tool_call_id": "tc_1"},
        {"role": "tool", "content": "headline news", "tool_call_id": "tc_2"},
        {"role": "assistant", "content": "Here are the results."},
    ]

    result = _strip_tool_content_from_messages(messages)

    # user, assistant (flattened), user (merged tool results), assistant
    assert len(result) == 4
    roles = [m["role"] for m in result]
    assert roles == ["user", "assistant", "user", "assistant"]

    # Both tool results merged into one user message
    merged = result[2]["content"]
    assert isinstance(merged, str)
    assert "tc_1" in merged
    assert "sunny 72F" in merged
    assert "tc_2" in merged
    assert "headline news" in merged


def test_no_tool_choice_sent_when_no_tools(default_multi_llm: LitellmTransport) -> None:
    """Regression test for providers (e.g. Fireworks) that reject tool_choice=null.

    When no tools are provided, tool_choice must not be forwarded to
    litellm.completion() at all — not even as None.
    """
    messages: LanguageModelInput = [UserMessage(content="Hello!")]

    mock_stream_chunks = [
        litellm.ModelResponse(
            id="chatcmpl-123",
            choices=[
                litellm.Choices(
                    delta=_create_delta(content="Hello!"),
                    finish_reason="stop",
                    index=0,
                )
            ],
            model="gpt-3.5-turbo",
        ),
    ]

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = mock_stream_chunks

        default_multi_llm.invoke(messages, tools=None)

        _, kwargs = mock_completion.call_args
        assert "tool_choice" not in kwargs, (
            "tool_choice must not be sent to providers when no tools are provided"
        )


_TOOL_CHOICE_DOWNGRADE_TOOLS: list[dict[str, JsonValue]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        },
    }
]


@pytest.mark.parametrize(
    "model_provider, model_name",
    [
        (LlmProviderNames.OPENROUTER, "qwen/qwen3.7-plus"),
        (LlmProviderNames.ANTHROPIC, "claude-sonnet-5"),
        (LlmProviderNames.OPENROUTER, "z-ai/glm-5.3"),
    ],
)
def test_required_tool_choice_downgraded_to_auto(
    model_provider: str, model_name: str
) -> None:
    """Claude, Qwen thinking, and GLM models reject/degrade required
    tool_choice, so it must be sent to the provider as AUTO instead."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=32000,
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Weather in NYC?")]
        list(
            llm.stream(
                messages,
                tools=_TOOL_CHOICE_DOWNGRADE_TOOLS,
                tool_choice=ToolChoiceOptions.REQUIRED,
            )
        )

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["tool_choice"] == ToolChoiceOptions.AUTO


def test_qwen_only_in_deployment_name_downgrades_tool_choice() -> None:
    """is_qwen_model must also check deployment_name, same identity gap as
    is_claude_model above it. A Qwen model reachable only by alias must
    still get the required->auto downgrade or the provider 400s."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.LITELLM_PROXY,
        model_name="foundry-deploy-3",
        deployment_name="qwen/qwen3.7-plus",
        max_input_tokens=32000,
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Weather in NYC?")]
        list(
            llm.stream(
                messages,
                tools=_TOOL_CHOICE_DOWNGRADE_TOOLS,
                tool_choice=ToolChoiceOptions.REQUIRED,
            )
        )

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["tool_choice"] == ToolChoiceOptions.AUTO


def test_required_tool_choice_preserved_for_other_models(
    default_multi_llm: LitellmTransport,
) -> None:
    """Models without the thinking-mode constraint must keep required."""
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Weather in NYC?")]
        list(
            default_multi_llm.stream(
                messages,
                tools=_TOOL_CHOICE_DOWNGRADE_TOOLS,
                tool_choice=ToolChoiceOptions.REQUIRED,
            )
        )

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["tool_choice"] == ToolChoiceOptions.REQUIRED


def test_named_tool_choice_serialized_for_litellm(
    default_multi_llm: LitellmTransport,
) -> None:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Weather in NYC?")]
        list(
            default_multi_llm.stream(
                messages,
                tools=_TOOL_CHOICE_DOWNGRADE_TOOLS,
                tool_choice=NamedToolChoice(name="get_weather"),
            )
        )

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["tool_choice"] == {
            "type": "function",
            "function": {"name": "get_weather"},
        }


def test_named_tool_choice_not_downgraded_for_claude_model() -> None:
    """Unlike REQUIRED, a NamedToolChoice must pass through unchanged even for
    models that downgrade tool_choice=required."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.ANTHROPIC,
        model_name="claude-sonnet-5",
        max_input_tokens=32000,
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Weather in NYC?")]
        list(
            llm.stream(
                messages,
                tools=_TOOL_CHOICE_DOWNGRADE_TOOLS,
                tool_choice=NamedToolChoice(name="get_weather"),
            )
        )

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["tool_choice"] == {
            "type": "function",
            "function": {"name": "get_weather"},
        }


def test_named_tool_choice_skips_legacy_claude_thinking() -> None:
    """Anthropic rejects thinking.type=enabled combined with a forced tool, so
    a NamedToolChoice must suppress the legacy budget_tokens thinking param."""
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.ANTHROPIC,
        model_name="claude-sonnet-4-5",
        max_input_tokens=32000,
    )

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=True),
    ):
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Weather in NYC?")]
        list(
            llm.stream(
                messages,
                tools=_TOOL_CHOICE_DOWNGRADE_TOOLS,
                tool_choice=NamedToolChoice(name="get_weather"),
                reasoning_effort=ReasoningEffort.HIGH,
            )
        )

        kwargs = mock_completion.call_args.kwargs
        assert "thinking" not in kwargs
        assert kwargs["tool_choice"] == {
            "type": "function",
            "function": {"name": "get_weather"},
        }


def test_bifrost_normalizes_api_base_in_model_kwargs() -> None:
    llm = LitellmTransport(
        api_key="test_key",
        api_base="https://bifrost.example.com/",
        model_provider=LlmProviderNames.BIFROST,
        model_name="anthropic/claude-sonnet-4-6",
        max_input_tokens=32000,
    )

    assert llm._custom_llm_provider == "openai"
    assert llm._api_base == "https://bifrost.example.com/v1"
    assert llm._model_kwargs["api_base"] == "https://bifrost.example.com/v1"


def test_prompt_contains_tool_call_history_true() -> None:
    from onyx.llm.multi_llm import _prompt_contains_tool_call_history

    messages: LanguageModelInput = [
        UserMessage(content="What's the weather?"),
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id="tc_1",
                    function=FunctionCall(name="get_weather", arguments="{}"),
                )
            ],
        ),
    ]
    assert _prompt_contains_tool_call_history(messages) is True


def test_prompt_contains_tool_call_history_false_no_tools() -> None:
    from onyx.llm.multi_llm import _prompt_contains_tool_call_history

    messages: LanguageModelInput = [
        UserMessage(content="Hello"),
        AssistantMessage(content="Hi there!"),
    ]
    assert _prompt_contains_tool_call_history(messages) is False


def test_prompt_contains_tool_call_history_false_user_only() -> None:
    from onyx.llm.multi_llm import _prompt_contains_tool_call_history

    messages: LanguageModelInput = [UserMessage(content="Hello")]
    assert _prompt_contains_tool_call_history(messages) is False


def test_bedrock_claude_drops_thinking_when_thinking_blocks_missing() -> None:
    """When thinking is enabled but assistant messages with tool_calls lack
    thinking_blocks, the thinking param must be dropped to avoid the Bedrock
    BadRequestError about missing thinking blocks."""
    llm = LitellmTransport(
        api_key=None,
        model_provider=LlmProviderNames.BEDROCK,
        model_name="anthropic.claude-sonnet-4-20250514-v1:0",
        max_input_tokens=200000,
    )

    messages: LanguageModelInput = [
        UserMessage(content="What's the weather?"),
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id="tc_1",
                    function=FunctionCall(
                        name="get_weather",
                        arguments='{"city": "Paris"}',
                    ),
                )
            ],
        ),
        ToolMessage(
            content="22°C sunny",
            tool_call_id="tc_1",
        ),
    ]

    tools: list[dict[str, JsonValue]] = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        }
    ]

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=True),
    ):
        mock_completion.return_value = []

        list(llm.stream(messages, tools=tools, reasoning_effort=ReasoningEffort.HIGH))

        kwargs = mock_completion.call_args.kwargs
        assert "thinking" not in kwargs, (
            "thinking param should be dropped when thinking_blocks are missing "
            "from assistant messages with tool_calls"
        )


def test_bedrock_claude_keeps_thinking_when_no_tool_history() -> None:
    """When thinking is enabled and there are no historical assistant messages
    with tool_calls, the thinking param should be preserved."""
    llm = LitellmTransport(
        api_key=None,
        model_provider=LlmProviderNames.BEDROCK,
        model_name="anthropic.claude-sonnet-4-20250514-v1:0",
        max_input_tokens=200000,
    )

    messages: LanguageModelInput = [
        UserMessage(content="What's the weather?"),
    ]

    tools: list[dict[str, JsonValue]] = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        }
    ]

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=True),
    ):
        mock_completion.return_value = []

        list(llm.stream(messages, tools=tools, reasoning_effort=ReasoningEffort.HIGH))

        kwargs = mock_completion.call_args.kwargs
        assert "thinking" in kwargs, (
            "thinking param should be preserved when no assistant messages "
            "with tool_calls exist in history"
        )
        assert kwargs["thinking"]["type"] == "enabled"


def test_bifrost_claude_includes_allowed_openai_params() -> None:
    llm = LitellmTransport(
        api_key="test_key",
        api_base="https://bifrost.example.com",
        model_provider=LlmProviderNames.BIFROST,
        model_name="anthropic/claude-sonnet-4-6",
        max_input_tokens=32000,
    )

    messages: LanguageModelInput = [UserMessage(content="Use a tool if needed")]
    tools: list[dict[str, JsonValue]] = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up data",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]
    mock_stream_chunks = [
        litellm.ModelResponse(
            id="chatcmpl-123",
            choices=[
                litellm.Choices(
                    delta=_create_delta(content="Done"),
                    finish_reason="stop",
                    index=0,
                )
            ],
            model="anthropic/claude-sonnet-4-6",
        ),
    ]

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = mock_stream_chunks

        llm.invoke(messages, tools=tools)

        kwargs = mock_completion.call_args.kwargs
        assert kwargs["model"] == "anthropic/claude-sonnet-4-6"
        assert kwargs["base_url"] == "https://bifrost.example.com/v1"
        assert kwargs["custom_llm_provider"] == "openai"
        assert kwargs["allowed_openai_params"] == ["tool_choice"]


# Provider credentials use request arguments.


def _simple_stream_chunks(model_name: str) -> list[litellm.ModelResponse]:
    return [
        litellm.ModelResponse(
            id="chatcmpl-123",
            choices=[
                litellm.Choices(
                    delta=_create_delta(content="Hi"),
                    finish_reason="stop",
                    index=0,
                )
            ],
            model=model_name,
        ),
    ]


def test_custom_config_bearer_token_clobbers_provider_api_key() -> None:
    llm = LitellmTransport(
        api_key="stored-key",
        model_provider=LlmProviderNames.BEDROCK,
        model_name="anthropic.claude-3-sonnet-20240229-v1:0",
        max_input_tokens=200000,
        custom_config={"AWS_BEARER_TOKEN_BEDROCK": "bearer-token"},
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = _simple_stream_chunks(
            "anthropic.claude-3-sonnet-20240229-v1:0"
        )
        llm.invoke([UserMessage(content="Hi")])

    assert mock_completion.call_args.kwargs["api_key"] == "bearer-token"


def test_generic_custom_provider_api_key_reaches_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider credentials use explicit arguments and preserve process environment."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    llm = LitellmTransport(
        api_key=None,
        model_provider="groq",
        model_name="llama-3.3-70b-versatile",
        max_input_tokens=8192,
        custom_config={"GROQ_API_KEY": "groq-key"},
    )

    env_during_call: dict[str, str | None] = {}

    def fake_completion(
        **kwargs: Any,
    ) -> litellm.ModelResponse | list[litellm.ModelResponse]:
        env_during_call["GROQ_API_KEY"] = os.environ.get("GROQ_API_KEY")
        return _simple_completion_result(kwargs, "llama-3.3-70b-versatile")

    with (
        patch("litellm.completion", side_effect=fake_completion) as mock_completion,
    ):
        llm.invoke([UserMessage(content="Hi")])

    assert mock_completion.call_args.kwargs["api_key"] == "groq-key"
    assert env_during_call["GROQ_API_KEY"] is None


def _openai_compatible_llm(
    model_name: str, deployment_name: str | None = None
) -> LitellmTransport:
    return LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.OPENAI,
        model_name=model_name,
        deployment_name=deployment_name,
        api_base="http://vllm.internal:8000/v1",
        max_input_tokens=32000,
    )


def _tool_cycle_prompt() -> LanguageModelInput:
    return [
        UserMessage(content="What's the weather in Paris?"),
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    type="function",
                    id="call_1",
                    function=FunctionCall(name="get_weather", arguments="{}"),
                )
            ],
        ),
        ToolMessage(content="Sunny, 21C", tool_call_id="call_1"),
        UserMessage(content="Remember to cite your sources."),
    ]


def _completion_message_roles(llm: LitellmTransport) -> list[str]:
    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
    ):
        mock_completion.return_value = []
        list(llm.stream(_tool_cycle_prompt()))
        return [m["role"] for m in mock_completion.call_args.kwargs["messages"]]


@pytest.mark.parametrize(
    "model_name",
    ["mistralai/Mistral-Small-3.2-24B-Instruct", "Codestral-2501", "pixtral-large"],
)
def test_tool_user_bridge_for_mistral_family_behind_openai_compatible(
    model_name: str,
) -> None:
    """Mistral-family models served behind OpenAI-compatible endpoints (e.g.
    vLLM) reject user-after-tool ordering; the bridge must fire on the model
    name alone (#12503)."""
    roles = _completion_message_roles(_openai_compatible_llm(model_name))
    tool_idx = roles.index("tool")
    assert roles[tool_idx + 1 :] == ["assistant", "user"]


def test_tool_user_bridge_checks_model_name_despite_deployment_alias() -> None:
    """A non-Mistral deployment alias must not shadow a Mistral model name."""
    roles = _completion_message_roles(
        _openai_compatible_llm("mistral-small-2506", deployment_name="prod-chat")
    )
    tool_idx = roles.index("tool")
    assert roles[tool_idx + 1 :] == ["assistant", "user"]


def test_tool_user_bridge_not_inserted_for_other_models() -> None:
    roles = _completion_message_roles(_openai_compatible_llm("glm-4.7"))
    tool_idx = roles.index("tool")
    assert roles[tool_idx + 1 :] == ["user"]


class _PingStream:
    """A stream that emits an empty keepalive 'ping' forever, like a stalled LLM call."""

    def __iter__(self) -> "_PingStream":
        return self

    def __next__(self) -> object:
        time.sleep(0.005)  # a packet keeps arriving, resetting any per-read timeout
        return object()


def test_consume_stream_completes_within_budget() -> None:
    deadline = time.monotonic() + 5
    assert _consume_stream_until_deadline(iter([1, 2, 3]), deadline) == [1, 2, 3]


def test_consume_stream_ping_flood_trips_total_timeout() -> None:
    start = time.monotonic()

    with pytest.raises(LLMTimeoutError):
        _consume_stream_until_deadline(_PingStream(), time.monotonic() + 0.05)

    # unwound promptly via the raise, not blocked on the ping flood
    assert time.monotonic() - start < 2.0


@pytest.mark.parametrize(
    "total_timeout_override, expected_read_timeout",
    [
        (30, 30),  # total below the socket read timeout -> read timeout capped at it
        (300, 60),  # total above it -> read timeout unchanged
        (None, 60),  # no total -> read timeout unchanged
    ],
)
def test_invoke_caps_read_timeout_at_total_budget(
    total_timeout_override: int | None, expected_read_timeout: int
) -> None:
    # The deadline is only checked between chunks, so the per-read timeout must be
    # capped at the total or a blocking read could overshoot a sub-read-timeout budget.
    llm = LitellmTransport(
        api_key="test_key",
        model_provider=LlmProviderNames.LITELLM_PROXY,
        model_name="claude-haiku-4-5",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.LITELLM_PROXY,
            model_name="claude-haiku-4-5",
        ),
    )
    chunk = litellm.ModelResponse(
        id="chatcmpl-1",
        choices=[
            litellm.Choices(
                delta=_create_delta(content="hi"),
                finish_reason="stop",
                index=0,
            )
        ],
        model="claude-haiku-4-5",
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = [chunk]
        llm.invoke([UserMessage(content="Hi")], total_timeout_s=total_timeout_s)
        sent_timeout = mock_completion.call_args.kwargs["timeout"]
        assert total_timeout_s - 1 < sent_timeout <= total_timeout_s


def test_policy_extra_body_keeps_deployment_siblings_under_the_same_key() -> None:
    """The OpenRouter retention policy sets one key under `provider`. The
    deployment's other keys under `provider` must survive that merge."""
    llm = LitellmTransport(
        api_key="or-test-key",
        model_provider=LlmProviderNames.OPENROUTER,
        model_name="openai/gpt-5.6",
        max_input_tokens=128_000,
        model_kwargs={"extra_body": {"provider": {"data_collection": "deny"}}},
        extra_body={"provider": {"order": ["Azure"], "allow_fallbacks": False}},
    )

    assert isinstance(llm._model_kwargs["extra_body"], dict)
    assert llm._model_kwargs["extra_body"]["provider"] == {
        "order": ["Azure"],
        "allow_fallbacks": False,
        "data_collection": "deny",
    }


def test_track_llm_cost_prices_cache_creation_at_write_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = LitellmTransport(
        api_key="managed-key",
        model_provider=LlmProviderNames.ANTHROPIC,
        model_name="claude-sonnet-4-5",
        max_input_tokens=200000,
    )
    db_session = MagicMock()

    @contextmanager
    def _fake_session() -> Iterator[Any]:
        yield db_session

    monkeypatch.setattr(
        "onyx.server.usage_limits.is_usage_limits_enabled", lambda: True
    )
    monkeypatch.setattr(
        "onyx.server.usage_limits.is_onyx_managed_api_key", lambda _key: True
    )
    monkeypatch.setattr(
        "onyx.db.engine.sql_engine.get_session_with_current_tenant", _fake_session
    )
    monkeypatch.setattr(
        "onyx.llm.cost.cost_overrides.get_override",
        lambda _session, _model, _provider: None,
    )
    increment_usage = MagicMock()
    monkeypatch.setattr("onyx.db.usage.increment_usage", increment_usage)

    llm._track_llm_cost(
        Usage(
            prompt_tokens=3000,
            completion_tokens=0,
            total_tokens=3000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=2000,
        )
    )

    assert increment_usage.call_args.args[2] == pytest.approx(1.05)


@pytest.mark.parametrize("provider", ["openai", "bedrock", "vertex_ai"])
def test_environment_only_request_settings_are_rejected(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REQUEST_ENV_SECRET", "deployment-value")
    with pytest.raises(
        ValueError, match="Configure environment-only settings in the deployment"
    ):
        LitellmTransport(
            api_key="test-key",
            model_provider=provider,
            model_name="test-model",
            max_input_tokens=1000,
            custom_config={"REQUEST_ENV_SECRET": "request-value"},
        )
    assert os.environ["REQUEST_ENV_SECRET"] == "deployment-value"


def test_request_credentials_do_not_enter_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "deployment-secret")
    entered = threading.Barrier(2)
    received: list[str] = []
    errors: list[BaseException] = []

    def completion(**kwargs: Any) -> list[litellm.ModelResponse]:
        entered.wait(timeout=3)
        received.append(kwargs["aws_secret_access_key"])
        assert os.environ["AWS_SECRET_ACCESS_KEY"] == "deployment-secret"
        return _simple_stream_chunks("anthropic.claude-3-sonnet-20240229-v1:0")

    def invoke(secret: str) -> None:
        try:
            provider = LitellmTransport(
                api_key=None,
                model_provider="bedrock",
                model_name="anthropic.claude-3-sonnet-20240229-v1:0",
                max_input_tokens=1000,
                custom_config={
                    "AWS_SECRET_ACCESS_KEY": secret,
                    "AWS_ACCESS_KEY_ID": "key",
                    "BEDROCK_AUTH_METHOD": "iam",
                },
            )
            provider.invoke([UserMessage(content="hello")])
        except BaseException as error:
            errors.append(error)

    with patch("litellm.completion", side_effect=completion):
        threads = [
            threading.Thread(target=invoke, args=(secret,))
            for secret in ("first", "second")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()
    assert not errors
    assert sorted(received) == ["first", "second"]
    assert os.environ["AWS_SECRET_ACCESS_KEY"] == "deployment-secret"
