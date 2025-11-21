from onyx.chat.models import PromptConfig
from onyx.chat.turn.context_handler.reminder import maybe_append_reminder
from onyx.llm.message_types import ChatCompletionMessage


def test_reminder_handler_with_reminder() -> None:
    """Test that reminder is appended when reminder is provided."""
    reminder_text = "Test reminder message"
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions=None,
        reminder=reminder_text,
        datetime_aware=False,
    )
    agent_turn_messages: list[ChatCompletionMessage] = [
        {"role": "assistant", "content": "Assistant response"},
    ]

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    # Should append a reminder message
    assert len(result) == 2
    assert result[0]["role"] == "assistant"
    assert result[1]["role"] == "user"
    assert reminder_text in str(result[1]["content"])


def test_reminder_handler_without_reminder() -> None:
    """Test that no reminder is appended when reminder field is empty."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="Test system prompt",
        custom_instructions=None,
        reminder="",  # Empty reminder
        datetime_aware=False,
    )
    agent_turn_messages: list[ChatCompletionMessage] = [
        {"role": "assistant", "content": "Assistant message"},
    ]

    result = maybe_append_reminder(
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    # Should return original messages unchanged since reminder is empty
    assert len(result) == 1
    assert result[0]["role"] == "assistant"
