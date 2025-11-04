from collections.abc import Sequence

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import AssistantMessageWithToolCalls
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import OutputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage
from onyx.agents.agent_sdk.message_types import ToolCall
from onyx.agents.agent_sdk.message_types import ToolCallFunction
from onyx.agents.agent_sdk.message_types import ToolMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.models import PromptConfig
from onyx.chat.turn.context_handler.task_prompt import add_reminder
from onyx.prompts.chat_prompts import OPEN_URL_REMINDER


def test_task_prompt_handler_with_no_user_messages() -> None:
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instruction="Test system prompt",
        reminder="Test task prompt",
        datetime_aware=False,
    )
    current_user_message: UserMessage = UserMessage(
        role="user",
        content=[InputTextContent(type="input_text", text="Current query")],
    )
    agent_turn_messages: Sequence[AgentSDKMessage] = [
        AssistantMessageWithContent(
            role="assistant",
            content=[OutputTextContent(type="output_text", text="Assistant message 1")],
        ),
        AssistantMessageWithContent(
            role="assistant",
            content=[OutputTextContent(type="output_text", text="Assistant message 2")],
        ),
    ]

    result = add_reminder(
        current_user_message,
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    assert len(result) == 3
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "assistant"
    assert result[2].get("role") == "user"


def test_task_prompt_handler_basic() -> None:
    """Test that add_reminder appends task prompt without removing previous user messages.

    Note: The removal of previous user messages is now handled by the
    remove_middle_user_messages context handler, not by add_reminder.
    """
    task_prompt = "reminder!"
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instruction="Test system prompt",
        reminder=task_prompt,
        datetime_aware=False,
    )
    current_user_message: UserMessage = UserMessage(
        role="user",
        content=[InputTextContent(type="input_text", text="Query")],
    )
    agent_turn_messages: Sequence[AgentSDKMessage] = [
        SystemMessage(
            role="system",
            content=[InputTextContent(type="input_text", text="hi")],
        ),
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"queries": ["hi"]}',
                        name="internal_search",
                    ),
                    id="call_1",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool message 1",
            tool_call_id="call_1",
        ),
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="old reminder")],
        ),
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"queries": ["hi"]}',
                        name="internal_search",
                    ),
                    id="call_1",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool message 1",
            tool_call_id="call_1",
        ),
    ]

    result = add_reminder(
        current_user_message,
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    # With the new behavior, add_reminder just appends, so we have 7 messages
    # (6 original + 1 new reminder)
    assert len(result) == 7
    assert result[0].get("role") == "system"
    assert result[1].get("role") == "assistant"
    assert result[2].get("role") == "tool"
    assert result[3].get("role") == "user"  # Old reminder is preserved
    assert result[4].get("role") == "assistant"
    assert result[5].get("role") == "tool"
    assert result[6].get("role") == "user"  # New reminder appended
    # Type narrow to UserMessage after checking role
    last_msg = result[6]
    if last_msg.get("role") == "user":
        user_msg: UserMessage = last_msg  # type: ignore[assignment]
        # Content is now a list of InputTextContent items
        assert isinstance(user_msg["content"], list)
        assert len(user_msg["content"]) > 0


def test_task_prompt_handler_with_web_search() -> None:
    """Test that web_search parameter is properly handled."""
    task_prompt = "reminder!"
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt=task_prompt,
        datetime_aware=False,
    )
    current_user_message: UserMessage = UserMessage(
        role="user",
        content=[InputTextContent(type="input_text", text="Query")],
    )
    agent_turn_messages: Sequence[AgentSDKMessage] = [
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"query": "test query"}',
                        name="web_search",
                    ),
                    id="call_1",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool message 1",
            tool_call_id="call_1",
        ),
    ]

    result = add_reminder(
        current_user_message,
        agent_turn_messages,
        prompt_config,
        should_cite_documents=True,
        last_iteration_included_web_search=True,
    )

    assert len(result) == 3
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "tool"
    assert result[2].get("role") == "user"
    # Type narrow to UserMessage after checking role
    last_msg = result[2]
    if last_msg.get("role") == "user":
        user_msg: UserMessage = last_msg  # type: ignore[assignment]
        assert isinstance(user_msg["content"], list)
        assert len(user_msg["content"]) > 0
        first_content = user_msg["content"][0]
        # Type narrow to InputTextContent
        text_content: InputTextContent = first_content  # type: ignore[assignment]
        assert OPEN_URL_REMINDER in text_content["text"]
