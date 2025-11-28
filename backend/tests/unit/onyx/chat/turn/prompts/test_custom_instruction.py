"""Tests for add_custom_instruction context handler."""

from typing import cast

from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.models import PromptConfig
from onyx.chat.turn.prompts.custom_instruction import build_custom_instructions


def test_with_custom_instruction() -> None:
    """Test that custom instruction is added when present."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Be concise and friendly.",
        reminder="Answer the question.",
        datetime_aware=False,
    )

    result = build_custom_instructions(prompt_config)

    # Should add custom instruction user message
    assert len(result) == 1
    assert result[0].get("role") == "user"

    # Verify custom instruction content
    user_msg = cast(UserMessage, result[0])
    text_content = cast(InputTextContent, user_msg["content"][0])
    assert "Be concise and friendly." in text_content["text"]


def test_without_custom_instruction() -> None:
    """Test that no message is added when custom_instruction is absent."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions=None,
        reminder="Answer the question.",
        datetime_aware=False,
    )

    result = build_custom_instructions(prompt_config)

    # Should have no messages added
    assert len(result) == 0
