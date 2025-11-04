"""Tests for remove_middle_user_messages context handler."""

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import AssistantMessageWithToolCalls
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import OutputTextContent
from onyx.agents.agent_sdk.message_types import ToolCall
from onyx.agents.agent_sdk.message_types import ToolCallFunction
from onyx.agents.agent_sdk.message_types import ToolMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.turn.context_handler.remove_user_messages import (
    remove_middle_user_messages,
)


def test_remove_user_messages_basic() -> None:
    """Test that user messages are removed from agent turn messages."""
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
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="Reminder: Answer well")],
        ),
    ]

    result = remove_middle_user_messages(agent_turn_messages)

    # Should only have assistant and tool messages
    assert len(result) == 2
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "tool"


def test_remove_user_messages_multiple() -> None:
    """Test that multiple user messages are removed."""
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
            content="Tool response 1",
            tool_call_id="call_1",
        ),
        UserMessage(
            role="user",
            content=[
                InputTextContent(type="input_text", text="Custom Instructions: Be nice")
            ],
        ),
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="Reminder: Answer well")],
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
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="Another reminder")],
        ),
    ]

    result = remove_middle_user_messages(agent_turn_messages)

    # Should only have assistant and tool messages
    assert len(result) == 4
    assert all(msg.get("role") in ["assistant", "tool"] for msg in result)


def test_remove_user_messages_no_user_messages() -> None:
    """Test that function works when there are no user messages."""
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

    result = remove_middle_user_messages(agent_turn_messages)

    # Should have same messages
    assert len(result) == 2
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "tool"


def test_remove_user_messages_preserves_order() -> None:
    """Test that the order of non-user messages is preserved."""
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
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="User message 1")],
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
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="User message 2")],
        ),
        AssistantMessageWithContent(
            role="assistant",
            content=[OutputTextContent(type="output_text", text="Final answer")],
        ),
    ]

    result = remove_middle_user_messages(agent_turn_messages)

    # Should preserve order of non-user messages
    assert len(result) == 5
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "tool"
    assert result[2].get("role") == "assistant"
    assert result[3].get("role") == "tool"
    assert result[4].get("role") == "assistant"
