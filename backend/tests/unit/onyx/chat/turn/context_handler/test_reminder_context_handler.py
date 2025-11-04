from collections.abc import Sequence
from typing import cast

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import OutputTextContent
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.models import PromptConfig
from onyx.chat.turn.context_handler.reminder import maybe_append_reminder


def test_reminder_handler_with_reminder() -> None:
    """Test that reminder is appended when reminder is provided."""
    reminder_text = "Test reminder message"
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions=None,
        reminder=reminder_text,
        datetime_aware=False,
    )
    agent_turn_messages: Sequence[AgentSDKMessage] = [
        AssistantMessageWithContent(
            role="assistant",
            content=[OutputTextContent(type="output_text", text="Assistant response")],
        ),
    ]

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    # Should append a reminder message
    assert len(result) == 2
    assert cast(AssistantMessageWithContent, result[0])["role"] == "assistant"
    assert cast(UserMessage, result[1])["role"] == "user"
    assert isinstance(cast(UserMessage, result[1])["content"], list)
    assert cast(UserMessage, result[1])["content"][0]["type"] == "input_text"
    assert (
        reminder_text
        in cast(InputTextContent, cast(UserMessage, result[1])["content"][0])["text"]
    )


def test_reminder_handler_without_reminder() -> None:
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
            content=[OutputTextContent(type="output_text", text="Assistant message")],
        ),
    ]

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    # Should return original messages unchanged since reminder is empty
    assert len(result) == 1
    assert cast(AssistantMessageWithContent, result[0])["role"] == "assistant"
