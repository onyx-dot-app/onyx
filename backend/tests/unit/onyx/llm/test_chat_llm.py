from unittest.mock import patch

import litellm
import pytest
from litellm.types.utils import ChatCompletionDeltaToolCall
from litellm.types.utils import Delta
from litellm.types.utils import Function as LiteLLMFunction

from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.llm.chat_llm import LitellmLLM
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import AssistantMessage
from onyx.llm.models import FunctionCall
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ToolCall
from onyx.llm.models import UserMessage
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
    model_provider = "openai"
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
        # Create a mock response with multiple tool calls using litellm objects
        mock_response = litellm.ModelResponse(
            id="chatcmpl-123",
            choices=[
                litellm.Choices(
                    finish_reason="tool_calls",
                    index=0,
                    message=litellm.Message(
                        content=None,
                        role="assistant",
                        tool_calls=[
                            litellm.ChatCompletionMessageToolCall(
                                id="call_1",
                                function=LiteLLMFunction(
                                    name="get_weather",
                                    arguments='{"location": "New York"}',
                                ),
                                type="function",
                            ),
                            litellm.ChatCompletionMessageToolCall(
                                id="call_2",
                                function=LiteLLMFunction(
                                    name="get_time", arguments='{"timezone": "EST"}'
                                ),
                                type="function",
                            ),
                        ],
                    ),
                )
            ],
            model="gpt-3.5-turbo",
            usage=litellm.Usage(
                prompt_tokens=50, completion_tokens=30, total_tokens=80
            ),
        )
        mock_completion.return_value = mock_response

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

        # Call the invoke method
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
            stream=False,
            temperature=0.0,  # Default value from GEN_AI_TEMPERATURE
            timeout=30,
            parallel_tool_calls=True,
            mock_response=MOCK_LLM_RESPONSE,
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
            parallel_tool_calls=True,
            mock_response=MOCK_LLM_RESPONSE,
            stream_options={"include_usage": True},
        )
