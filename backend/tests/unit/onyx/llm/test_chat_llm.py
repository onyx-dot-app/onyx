from unittest.mock import patch

import litellm
import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import HumanMessage
from litellm.types.utils import ChatCompletionDeltaToolCall
from litellm.types.utils import Delta
from litellm.types.utils import Function as LiteLLMFunction

from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.llm.chat_llm import LitellmLLM
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
        messages = [HumanMessage(content="What's the weather and time in New York?")]

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

        # Call the _invoke_implementation method
        result = default_multi_llm.invoke_langchain(messages, tools)

        # Assert that the result is an AIMessage
        assert isinstance(result, AIMessage)

        # Assert that the content is None (as per the mock response)
        assert result.content == ""

        # Assert that there are two tool calls
        assert len(result.tool_calls) == 2

        # Assert the details of the first tool call
        assert result.tool_calls[0]["id"] == "call_1"
        assert result.tool_calls[0]["name"] == "get_weather"
        assert result.tool_calls[0]["args"] == {"location": "New York"}

        # Assert the details of the second tool call
        assert result.tool_calls[1]["id"] == "call_2"
        assert result.tool_calls[1]["name"] == "get_time"
        assert result.tool_calls[1]["args"] == {"timezone": "EST"}

        # Verify that litellm.completion was called with the correct arguments
        mock_completion.assert_called_once_with(
            model="openai/gpt-3.5-turbo",
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
            parallel_tool_calls=False,
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
        messages = [HumanMessage(content="What's the weather and time in New York?")]

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
        stream_result = list(default_multi_llm.stream_langchain(messages, tools))

        # Assert that we received the correct number of chunks
        assert len(stream_result) == 3

        # Combine all chunks into a single AIMessage
        combined_result: AIMessage = AIMessageChunk(content="")
        for chunk in stream_result:
            combined_result += chunk  # type: ignore

        # Assert that the combined result matches our expectations
        assert isinstance(combined_result, AIMessage)
        assert combined_result.content == ""
        assert len(combined_result.tool_calls) == 2
        assert combined_result.tool_calls[0]["id"] == "call_1"
        assert combined_result.tool_calls[0]["name"] == "get_weather"
        assert combined_result.tool_calls[0]["args"] == {"location": "New York"}
        assert combined_result.tool_calls[1]["id"] == "call_2"
        assert combined_result.tool_calls[1]["name"] == "get_time"
        assert combined_result.tool_calls[1]["args"] == {"timezone": "EST"}

        # Verify that litellm.completion was called with the correct arguments
        mock_completion.assert_called_once_with(
            model="openai/gpt-3.5-turbo",
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
            parallel_tool_calls=False,
            mock_response=MOCK_LLM_RESPONSE,
            stream_options={"include_usage": True},
        )


def test_exclude_reasoning_config_for_anthropic_with_function_tool_choice() -> None:
    """Test that reasoning config is excluded for Anthropic models when using function tool choice."""
    # Create an Anthropic LLM
    anthropic_llm = LitellmLLM(
        api_key="test_key",
        timeout=30,
        model_provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        max_input_tokens=200000,
    )

    # Mock the litellm.completion function
    with patch("litellm.completion") as mock_completion:
        mock_response = litellm.ModelResponse(
            id="msg-123",
            choices=[
                litellm.Choices(
                    finish_reason="tool_use",
                    index=0,
                    message=litellm.Message(
                        content=None,
                        role="assistant",
                        tool_calls=[
                            litellm.ChatCompletionMessageToolCall(
                                id="call_1",
                                function=LiteLLMFunction(
                                    name="search",
                                    arguments='{"query": "test"}',
                                ),
                                type="function",
                            ),
                        ],
                    ),
                )
            ],
            model="claude-3-5-sonnet-20241022",
            usage=litellm.Usage(
                prompt_tokens=50, completion_tokens=30, total_tokens=80
            ),
        )
        mock_completion.return_value = mock_response

        messages = [HumanMessage(content="Test message")]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search for information",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            },
        ]

        # Call with a specific function tool choice
        anthropic_llm.invoke(messages, tools, tool_choice="search")

        # Verify that reasoning_effort and thinking are NOT passed to litellm.completion
        call_kwargs = mock_completion.call_args[1]
        assert "reasoning_effort" not in call_kwargs
        assert "thinking" not in call_kwargs
