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
from onyx.chat.turn.context_handler.reminder import maybe_append_reminder
from onyx.prompts.chat_prompts import OPEN_URL_REMINDER


def test_reminder_handler_with_no_user_messages() -> None:
    """Test that reminder is appended when there are only assistant messages."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Test system prompt",
        reminder="Test task prompt",
        datetime_aware=False,
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

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    assert len(result) == 3
    assert result[0]["role"] == "assistant"
    assert result[1]["role"] == "assistant"
    assert result[2]["role"] == "user"
    assert isinstance(result[2]["content"], list)
    assert result[2]["content"][0]["type"] == "input_text"


def test_reminder_handler_basic() -> None:
    """Test that maybe_append_reminder appends task prompt without removing previous user messages.

    Note: The removal of previous user messages is now handled by the
    remove_middle_user_messages context handler, not by maybe_append_reminder.
    """
    task_prompt = "reminder!"
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Test system prompt",
        reminder=task_prompt,
        datetime_aware=False,
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

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    # With the new behavior, maybe_append_reminder just appends, so we have 7 messages
    # (6 original + 1 new reminder)
    assert len(result) == 7
    assert result[0]["role"] == "system"
    assert result[1]["role"] == "assistant"
    assert result[2]["role"] == "tool"
    assert result[3]["role"] == "user"  # Old reminder is preserved
    assert result[4]["role"] == "assistant"
    assert result[5]["role"] == "tool"
    assert result[6]["role"] == "user"  # New reminder appended
    # Verify the appended reminder has correct structure
    assert isinstance(result[6]["content"], list)
    assert len(result[6]["content"]) > 0
    assert result[6]["content"][0]["type"] == "input_text"


def test_reminder_handler_with_web_search() -> None:
    """Test that web_search parameter is properly handled and OPEN_URL_REMINDER is included."""
    task_prompt = "reminder!"
    prompt_config = PromptConfig(
        default_behavior_system_prompt="Test system prompt",
        custom_instructions=None,
        reminder=task_prompt,
        datetime_aware=False,
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

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=True,
        last_iteration_included_web_search=True,
    )

    assert len(result) == 3
    assert result[0]["role"] == "assistant"
    assert result[1]["role"] == "tool"
    assert result[2]["role"] == "user"
    assert isinstance(result[2]["content"], list)
    assert len(result[2]["content"]) > 0
    assert result[2]["content"][0]["type"] == "input_text"
    assert OPEN_URL_REMINDER in result[2]["content"][0]["text"]


def test_reminder_handler_without_web_search() -> None:
    """Test that OPEN_URL_REMINDER is not included when web_search is False."""
    task_prompt = "reminder!"
    prompt_config = PromptConfig(
        default_behavior_system_prompt="Test system prompt",
        custom_instructions=None,
        reminder=task_prompt,
        datetime_aware=False,
    )
    agent_turn_messages: Sequence[AgentSDKMessage] = [
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"queries": ["test"]}',
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

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=True,
        last_iteration_included_web_search=False,
    )

    assert len(result) == 3
    assert result[2]["role"] == "user"
    assert isinstance(result[2]["content"], list)
    assert len(result[2]["content"]) > 0
    assert result[2]["content"][0]["type"] == "input_text"
    # Should NOT contain OPEN_URL_REMINDER when web_search is False
    assert OPEN_URL_REMINDER not in result[2]["content"][0]["text"]


def test_reminder_handler_with_empty_reminder() -> None:
    """Test that no reminder is appended when reminder field is empty."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="Test system prompt",
        custom_instructions=None,
        reminder="",  # Empty reminder
        datetime_aware=False,
    )
    agent_turn_messages: Sequence[AgentSDKMessage] = [
        AssistantMessageWithContent(
            role="assistant",
            content=[OutputTextContent(type="output_text", text="Assistant message 1")],
        ),
    ]

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    # Should return original messages unchanged since reminder is empty
    assert len(result) == 1
    assert result[0]["role"] == "assistant"


def test_reminder_handler_with_citation() -> None:
    """Test that CITATION_REMINDER is included when should_cite_documents is True."""
    from onyx.prompts.chat_prompts import CITATION_REMINDER

    task_prompt = "Please help!"
    prompt_config = PromptConfig(
        default_behavior_system_prompt="Test system prompt",
        custom_instructions=None,
        reminder=task_prompt,
        datetime_aware=False,
    )
    agent_turn_messages: Sequence[AgentSDKMessage] = [
        AssistantMessageWithContent(
            role="assistant",
            content=[OutputTextContent(type="output_text", text="Assistant message 1")],
        ),
    ]

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=True,
    )

    # Should append reminder with citation
    assert len(result) == 2
    assert result[1]["role"] == "user"
    assert isinstance(result[1]["content"], list)
    assert len(result[1]["content"]) > 0
    assert result[1]["content"][0]["type"] == "input_text"
    # Should contain both the task prompt and citation reminder
    reminder_text = result[1]["content"][0]["text"]
    assert task_prompt in reminder_text
    assert CITATION_REMINDER in reminder_text
