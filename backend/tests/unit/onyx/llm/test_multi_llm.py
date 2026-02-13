import os
import threading
import time
from typing import Any
from unittest.mock import ANY
from unittest.mock import patch

import litellm
import pytest
from litellm.types.utils import ChatCompletionDeltaToolCall
from litellm.types.utils import Delta
from litellm.types.utils import Function as LiteLLMFunction

from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import AssistantMessage
from onyx.llm.models import FunctionCall
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolCall
from onyx.llm.models import UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.utils import get_max_input_tokens


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
        role="assistant",
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
                        tool_calls_map[index][
                            "arguments"
                        ] += tool_call_delta.function.arguments

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
        role="assistant",
        content=accumulated_content if accumulated_content else None,
        tool_calls=tool_calls,
    )


@pytest.fixture
def default_multi_llm() -> LitellmLLM:
    model_provider = LlmProviderNames.OPENAI
    model_name = "gpt-3.5-turbo"

    return LitellmLLM(
        api_key="test_key",
        timeout=30,
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
    )


def test_multiple_tool_calls(default_multi_llm: LitellmLLM) -> None:
    # Mock the litellm.completion function
    with patch("litellm.completion") as mock_completion:
        # invoke() internally uses stream=True and reassembles via
        # stream_chunk_builder, so the mock must return stream chunks.
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(
                            role="assistant",
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
        tools = [
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
            tool_choice=None,
            stream=True,
            temperature=0.0,  # Default value from GEN_AI_TEMPERATURE
            timeout=30,
            max_tokens=None,
            client=ANY,  # HTTPHandler instance created per-request
            stream_options={"include_usage": True},
            parallel_tool_calls=True,
            mock_response=MOCK_LLM_RESPONSE,
            allowed_openai_params=["tool_choice"],
        )


def test_multiple_tool_calls_streaming(default_multi_llm: LitellmLLM) -> None:
    # Mock the litellm.completion function
    with patch("litellm.completion") as mock_completion:
        # Create a mock response with multiple tool calls using litellm objects
        mock_response = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(
                            role="assistant",
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

        tools = [
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
            tool_choice=None,
            stream=True,
            temperature=0.0,  # Default value from GEN_AI_TEMPERATURE
            timeout=30,
            max_tokens=None,
            client=ANY,  # HTTPHandler instance created per-stream
            stream_options={"include_usage": True},
            parallel_tool_calls=True,
            mock_response=MOCK_LLM_RESPONSE,
            allowed_openai_params=["tool_choice"],
        )


def test_vertex_stream_omits_stream_options() -> None:
    llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
        model_provider=LlmProviderNames.VERTEX_AI,
        model_name="claude-opus-4-5@20251101",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.VERTEX_AI,
            model_name="claude-opus-4-5@20251101",
        ),
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))

        kwargs = mock_completion.call_args.kwargs
        assert "stream_options" not in kwargs


def test_openai_auto_reasoning_effort_maps_to_medium() -> None:
    llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
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


def test_vertex_opus_4_5_omits_reasoning_effort() -> None:
    llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
        model_provider=LlmProviderNames.VERTEX_AI,
        model_name="claude-opus-4-5@20251101",
        max_input_tokens=get_max_input_tokens(
            model_provider=LlmProviderNames.VERTEX_AI,
            model_name="claude-opus-4-5@20251101",
        ),
    )

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.multi_llm.model_is_reasoning_model", return_value=True),
    ):
        mock_completion.return_value = []

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        list(llm.stream(messages))

        kwargs = mock_completion.call_args.kwargs
        assert "reasoning_effort" not in kwargs


def test_openai_chat_omits_reasoning_params() -> None:
    llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
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
                        delta=_create_delta(role="assistant", content="Hello"),
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


def test_user_identity_metadata_enabled(default_multi_llm: LitellmLLM) -> None:
    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.utils.SEND_USER_METADATA_TO_LLM_PROVIDER", True),
    ):
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(role="assistant", content="Hello"),
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
    default_multi_llm: LitellmLLM,
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
                        delta=_create_delta(role="assistant", content="Hello"),
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
    default_multi_llm: LitellmLLM,
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
                        delta=_create_delta(role="assistant", content="Hello"),
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

    llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
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
                        delta=_create_delta(role="assistant", content="Hello"),
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
    default_multi_llm: LitellmLLM,
) -> None:
    """Test that OpenAI models get an HTTPHandler client passed for invoke()."""
    from litellm import HTTPHandler

    with patch("litellm.completion") as mock_completion:
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(role="assistant", content="Hello"),
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
    default_multi_llm: LitellmLLM,
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


def test_anthropic_model_passes_no_client() -> None:
    """Test that non-OpenAI models (Anthropic) don't get a client passed."""
    llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
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
                        delta=_create_delta(role="assistant", content="Hello"),
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
        assert kwargs["client"] is None


def test_bedrock_model_passes_no_client() -> None:
    """Test that Bedrock models don't get a client passed."""
    llm = LitellmLLM(
        api_key=None,
        timeout=30,
        model_provider=LlmProviderNames.BEDROCK,
        model_name="anthropic.claude-3-sonnet-20240229-v1:0",
        max_input_tokens=200000,
    )

    with patch("litellm.completion") as mock_completion:
        mock_stream_chunks = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta=_create_delta(role="assistant", content="Hello"),
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
        assert kwargs["client"] is None


def test_azure_openai_model_uses_httphandler_client() -> None:
    """Test that Azure OpenAI models get an HTTPHandler client passed.

    Azure OpenAI uses the same responses API as OpenAI, so it needs
    the same HTTPHandler isolation to avoid connection pool conflicts.
    """
    from litellm import HTTPHandler

    llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
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
                        delta=_create_delta(role="assistant", content="Hello"),
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


def test_temporary_env_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    # Assign some environment variables
    EXPECTED_ENV_VARS = {
        "TEST_ENV_VAR": "test_value",
        "ANOTHER_ONE": "1",
        "THIRD_ONE": "2",
    }

    CUSTOM_CONFIG = {
        "TEST_ENV_VAR": "fdsfsdf",
        "ANOTHER_ONE": "3",
        "THIS_IS_RANDOM": "123213",
    }

    for env_var, value in EXPECTED_ENV_VARS.items():
        monkeypatch.setenv(env_var, value)

    model_provider = LlmProviderNames.OPENAI
    model_name = "gpt-3.5-turbo"

    llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
        model_kwargs={"metadata": {"foo": "bar"}},
        custom_config=CUSTOM_CONFIG,
    )

    # When custom_config is set, invoke() internally uses stream=True and
    # reassembles via stream_chunk_builder, so the mock must return stream chunks.
    mock_stream_chunks = [
        litellm.ModelResponse(
            id="chatcmpl-123",
            choices=[
                litellm.Choices(
                    delta=_create_delta(role="assistant", content="Hello"),
                    finish_reason="stop",
                    index=0,
                )
            ],
            model="gpt-3.5-turbo",
        ),
    ]

    def on_litellm_completion(
        **kwargs: dict[str, Any],  # noqa: ARG001
    ) -> list[litellm.ModelResponse]:
        # Validate that the environment variables are those in custom config
        for env_var, value in CUSTOM_CONFIG.items():
            assert env_var in os.environ
            assert os.environ[env_var] == value

        return mock_stream_chunks

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.utils.SEND_USER_METADATA_TO_LLM_PROVIDER", False),
    ):
        mock_completion.side_effect = on_litellm_completion

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        identity = LLMUserIdentity(user_id="user_123", session_id="session_abc")

        llm.invoke(messages, user_identity=identity)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert kwargs["stream"] is True
        assert "user" not in kwargs
        assert kwargs["metadata"]["foo"] == "bar"

        # Check that the environment variables are back to the original values
        for env_var, value in EXPECTED_ENV_VARS.items():
            assert env_var in os.environ
            assert os.environ[env_var] == value

        # Check that temporary env var from CUSTOM_CONFIG is no longer set
        assert "THIS_IS_RANDOM" not in os.environ


def test_temporary_env_cleanup_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify env vars are restored even when an exception occurs during LLM invocation."""
    # Assign some environment variables
    EXPECTED_ENV_VARS = {
        "TEST_ENV_VAR": "test_value",
        "ANOTHER_ONE": "1",
        "THIRD_ONE": "2",
    }

    CUSTOM_CONFIG = {
        "TEST_ENV_VAR": "fdsfsdf",
        "ANOTHER_ONE": "3",
        "THIS_IS_RANDOM": "123213",
    }

    for env_var, value in EXPECTED_ENV_VARS.items():
        monkeypatch.setenv(env_var, value)

    model_provider = LlmProviderNames.OPENAI
    model_name = "gpt-3.5-turbo"

    llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
        model_kwargs={"metadata": {"foo": "bar"}},
        custom_config=CUSTOM_CONFIG,
    )

    def on_litellm_completion_raises(**kwargs: dict[str, Any]) -> None:  # noqa: ARG001
        # Validate that the environment variables are those in custom config
        for env_var, value in CUSTOM_CONFIG.items():
            assert env_var in os.environ
            assert os.environ[env_var] == value

        # Simulate an error during LLM call
        raise RuntimeError("Simulated LLM API failure")

    with (
        patch("litellm.completion") as mock_completion,
        patch("onyx.llm.utils.SEND_USER_METADATA_TO_LLM_PROVIDER", False),
    ):
        mock_completion.side_effect = on_litellm_completion_raises

        messages: LanguageModelInput = [UserMessage(content="Hi")]
        identity = LLMUserIdentity(user_id="user_123", session_id="session_abc")

        with pytest.raises(RuntimeError, match="Simulated LLM API failure"):
            llm.invoke(messages, user_identity=identity)

        mock_completion.assert_called_once()

        # Check that the environment variables are back to the original values
        for env_var, value in EXPECTED_ENV_VARS.items():
            assert env_var in os.environ
            assert os.environ[env_var] == value

        # Check that temporary env var from CUSTOM_CONFIG is no longer set
        assert "THIS_IS_RANDOM" not in os.environ


@pytest.mark.parametrize("use_stream", [False, True], ids=["invoke", "stream"])
def test_multithreaded_custom_config_isolation(
    monkeypatch: pytest.MonkeyPatch,
    use_stream: bool,
) -> None:
    """Verify the env lock prevents concurrent LLM calls from seeing each other's custom_config.

    Two LitellmLLM instances with different custom_config dicts call invoke/stream
    concurrently. The _env_lock in temporary_env_and_lock serializes their access so
    each call only ever sees its own env vars—never the other's.
    """
    # Ensure these keys start unset
    monkeypatch.delenv("SHARED_KEY", raising=False)
    monkeypatch.delenv("LLM_A_ONLY", raising=False)
    monkeypatch.delenv("LLM_B_ONLY", raising=False)

    CONFIG_A = {
        "SHARED_KEY": "value_from_A",
        "LLM_A_ONLY": "a_secret",
    }
    CONFIG_B = {
        "SHARED_KEY": "value_from_B",
        "LLM_B_ONLY": "b_secret",
    }

    all_env_keys = list(set(list(CONFIG_A.keys()) + list(CONFIG_B.keys())))

    model_provider = LlmProviderNames.OPENAI
    model_name = "gpt-3.5-turbo"

    llm_a = LitellmLLM(
        api_key="key_a",
        timeout=30,
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
        custom_config=CONFIG_A,
    )
    llm_b = LitellmLLM(
        api_key="key_b",
        timeout=30,
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
        custom_config=CONFIG_B,
    )

    # Both invoke (with custom_config) and stream use stream=True at the
    # litellm level, so the mock must return stream chunks.
    mock_stream_chunks = [
        litellm.ModelResponse(
            id="chatcmpl-123",
            choices=[
                litellm.Choices(
                    delta=_create_delta(role="assistant", content="Hi"),
                    finish_reason="stop",
                    index=0,
                )
            ],
            model=model_name,
        ),
    ]

    # Track what each call observed inside litellm.completion.
    # Keyed by api_key so we can identify which LLM instance made the call.
    observed_envs: dict[str, dict[str, str | None]] = {}

    def fake_completion(**kwargs: Any) -> list[litellm.ModelResponse]:
        time.sleep(0.1)  # We expect someone to get caught on the lock
        api_key = kwargs.get("api_key", "")
        label = "A" if api_key == "key_a" else "B"

        snapshot: dict[str, str | None] = {}
        for key in all_env_keys:
            snapshot[key] = os.environ.get(key)
        observed_envs[label] = snapshot

        return mock_stream_chunks

    errors: list[Exception] = []

    def run_llm(llm: LitellmLLM) -> None:
        try:
            messages: LanguageModelInput = [UserMessage(content="Hi")]
            if use_stream:
                list(llm.stream(messages))
            else:
                llm.invoke(messages)
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
    assert "A" in observed_envs and "B" in observed_envs

    # Thread A must have seen its own config for SHARED_KEY, not B's
    assert observed_envs["A"]["SHARED_KEY"] == "value_from_A"
    assert observed_envs["A"]["LLM_A_ONLY"] == "a_secret"
    # A must NOT see B's exclusive key
    assert observed_envs["A"]["LLM_B_ONLY"] is None

    # Thread B must have seen its own config for SHARED_KEY, not A's
    assert observed_envs["B"]["SHARED_KEY"] == "value_from_B"
    assert observed_envs["B"]["LLM_B_ONLY"] == "b_secret"
    # B must NOT see A's exclusive key
    assert observed_envs["B"]["LLM_A_ONLY"] is None

    # After both calls, env should be clean
    assert os.environ.get("SHARED_KEY") is None
    assert os.environ.get("LLM_A_ONLY") is None
    assert os.environ.get("LLM_B_ONLY") is None


def test_multithreaded_invoke_without_custom_config_skips_env_lock() -> None:
    """Verify that invoke() without custom_config does not acquire the env lock.

    Two LitellmLLM instances without custom_config call invoke concurrently.
    Both should run with stream=False, never touch the env lock, and complete
    without blocking each other.
    """
    from onyx.llm import multi_llm as multi_llm_module

    model_provider = LlmProviderNames.OPENAI
    model_name = "gpt-3.5-turbo"

    llm_a = LitellmLLM(
        api_key="key_a",
        timeout=30,
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
    )
    llm_b = LitellmLLM(
        api_key="key_b",
        timeout=30,
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
    )

    mock_stream_chunks = [
        litellm.ModelResponse(
            id="chatcmpl-123",
            choices=[
                litellm.Choices(
                    delta=_create_delta(role="assistant", content="Hi"),
                    finish_reason="stop",
                    index=0,
                )
            ],
            model=model_name,
        ),
    ]

    call_kwargs: dict[str, dict[str, Any]] = {}

    def fake_completion(**kwargs: Any) -> list[litellm.ModelResponse]:
        api_key = kwargs.get("api_key", "")
        label = "A" if api_key == "key_a" else "B"
        call_kwargs[label] = kwargs
        return mock_stream_chunks

    errors: list[Exception] = []

    def run_llm(llm: LitellmLLM) -> None:
        try:
            messages: LanguageModelInput = [UserMessage(content="Hi")]
            llm.invoke(messages)
        except Exception as e:
            errors.append(e)

    with (
        patch("litellm.completion", side_effect=fake_completion),
        patch.object(
            multi_llm_module,
            "temporary_env_and_lock",
            wraps=multi_llm_module.temporary_env_and_lock,
        ) as mock_env_lock,
    ):
        t_a = threading.Thread(target=run_llm, args=(llm_a,))
        t_b = threading.Thread(target=run_llm, args=(llm_b,))

        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

    assert not errors, f"Thread errors: {errors}"
    assert "A" in call_kwargs and "B" in call_kwargs

    # invoke() always uses stream=True internally (reassembles via stream_chunk_builder)
    assert call_kwargs["A"]["stream"] is True
    assert call_kwargs["B"]["stream"] is True

    # The env lock context manager should never have been called
    mock_env_lock.assert_not_called()
