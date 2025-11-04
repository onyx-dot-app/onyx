"""Tests for add_custom_instruction context handler."""

from typing import cast

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithToolCalls
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import ToolCall
from onyx.agents.agent_sdk.message_types import ToolCallFunction
from onyx.agents.agent_sdk.message_types import ToolMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.models import PromptConfig
from onyx.chat.turn.context_handler.custom_instruction import append_custom_instruction


def test_add_custom_instruction_with_instruction() -> None:
    """Test that custom instruction is added when present in prompt_config."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Be concise and friendly.",
        reminder="Answer the question.",
        datetime_aware=False,
    )

    agent_turn_messages: list[AgentSDKMessage] = [
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"query": "test"}',
                        name="search",
                    ),
                    id="call_1",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool response",
            tool_call_id="call_1",
        ),
    ]

    result = append_custom_instruction(agent_turn_messages, prompt_config)

    # Should have original messages plus custom instruction user message
    assert len(result) == 3
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "tool"
    assert result[2].get("role") == "user"

    # Verify custom instruction content
    last_msg = result[2]
    assert last_msg.get("role") == "user"
    user_msg = cast(UserMessage, last_msg)
    assert len(user_msg["content"]) > 0
    first_content = user_msg["content"][0]
    text_content = cast(InputTextContent, first_content)
    assert "Be concise and friendly." in text_content["text"]


def test_add_custom_instruction_without_instruction() -> None:
    """Test that no message is added when custom_instruction is None."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions=None,
        reminder="Answer the question.",
        datetime_aware=False,
    )

    agent_turn_messages: list[AgentSDKMessage] = [
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"query": "test"}',
                        name="search",
                    ),
                    id="call_1",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool response",
            tool_call_id="call_1",
        ),
    ]

    result = append_custom_instruction(agent_turn_messages, prompt_config)

    # Should have same messages as input
    assert len(result) == 2
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "tool"


def test_add_custom_instruction_with_empty_string() -> None:
    """Test that no message is added when custom_instruction is empty string."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="",
        reminder="Answer the question.",
        datetime_aware=False,
    )

    agent_turn_messages: list[AgentSDKMessage] = [
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"query": "test"}',
                        name="search",
                    ),
                    id="call_1",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool response",
            tool_call_id="call_1",
        ),
    ]

    result = append_custom_instruction(agent_turn_messages, prompt_config)

    # Should have same messages as input (empty string is falsy)
    assert len(result) == 2
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "tool"


def test_add_custom_instruction_empty_messages() -> None:
    """Test that custom instruction is added even with empty input messages."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Always be polite.",
        reminder="Answer the question.",
        datetime_aware=False,
    )

    agent_turn_messages: list[AgentSDKMessage] = []

    result = append_custom_instruction(agent_turn_messages, prompt_config)

    # Should have just the custom instruction user message
    assert len(result) == 1
    assert result[0].get("role") == "user"

    # Verify custom instruction content
    user_msg: UserMessage = result[0]  # type: ignore[assignment]
    assert isinstance(user_msg["content"], list)
    assert len(user_msg["content"]) > 0
    first_content = user_msg["content"][0]
    if first_content["type"] == "input_text":
        text_content: InputTextContent = first_content  # type: ignore[assignment]
        assert "Custom Instructions:" in text_content["text"]
        assert "Always be polite." in text_content["text"]


def test_add_custom_instruction_preserves_order() -> None:
    """Test that custom instruction is appended at the end."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Be detailed.",
        reminder="Answer the question.",
        datetime_aware=False,
    )

    agent_turn_messages: list[AgentSDKMessage] = [
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"query": "test1"}',
                        name="search",
                    ),
                    id="call_1",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool response 1",
            tool_call_id="call_1",
        ),
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"query": "test2"}',
                        name="search",
                    ),
                    id="call_2",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool response 2",
            tool_call_id="call_2",
        ),
    ]

    result = append_custom_instruction(agent_turn_messages, prompt_config)

    # Should preserve original order and append custom instruction at end
    assert len(result) == 5
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "tool"
    assert result[2].get("role") == "assistant"
    assert result[3].get("role") == "tool"
    assert result[4].get("role") == "user"  # Custom instruction at the end
