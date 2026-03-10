"""
Tests for the USER_REMINDER message type handling in translate_history_to_llm_format.

These tests verify that:
1. USER_REMINDER messages are wrapped with <system-reminder> tags
2. The wrapped messages are converted to UserMessage type for the LLM
3. The tags are properly applied around the message content
4. CODE_BLOCK_MARKDOWN is prepended to system messages for models that need it
"""

import pytest

from onyx.chat.llm_step import translate_history_to_llm_format
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.prompts.chat_prompts import CODE_BLOCK_MARKDOWN
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_CLOSE
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_OPEN


def _ensure_list(
    result: list[ChatCompletionMessage] | ChatCompletionMessage,
) -> list[ChatCompletionMessage]:
    """Convert LanguageModelInput to a list for easier testing."""
    if isinstance(result, list):
        return result
    return [result]


@pytest.fixture
def mock_llm_config() -> LLMConfig:
    """Create a minimal LLMConfig for testing."""
    return LLMConfig(
        model_provider="openai",
        model_name="gpt-4o-mini",
        temperature=0.7,
        api_key="test-key",
        api_base=None,
        api_version=None,
        max_input_tokens=128000,
    )


class TestUserReminderMessageType:
    """Tests for USER_REMINDER message handling in translate_history_to_llm_format."""

    def test_user_reminder_wrapped_with_tags(self, mock_llm_config: LLMConfig) -> None:
        """Test that USER_REMINDER messages are wrapped with system-reminder tags."""
        reminder_text = "Remember to cite your sources."
        history = [
            ChatMessageSimple(
                message=reminder_text,
                token_count=10,
                message_type=MessageType.USER_REMINDER,
            )
        ]

        raw_result = translate_history_to_llm_format(history, mock_llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg, UserMessage)
        assert msg.role == "user"
        # Verify the content starts and ends with the proper tags
        assert isinstance(msg.content, str)
        assert msg.content.startswith(SYSTEM_REMINDER_TAG_OPEN)
        assert msg.content.endswith(SYSTEM_REMINDER_TAG_CLOSE)
        # Verify the original message is inside the tags
        assert reminder_text in msg.content

    def test_user_reminder_tag_format(self, mock_llm_config: LLMConfig) -> None:
        """Test the exact format of the system-reminder tag wrapping."""
        reminder_text = "This is a test reminder."
        history = [
            ChatMessageSimple(
                message=reminder_text,
                token_count=10,
                message_type=MessageType.USER_REMINDER,
            )
        ]

        raw_result = translate_history_to_llm_format(history, mock_llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg, UserMessage)
        expected_content = (
            f"{SYSTEM_REMINDER_TAG_OPEN}\n{reminder_text}\n{SYSTEM_REMINDER_TAG_CLOSE}"
        )
        assert msg.content == expected_content

    def test_user_reminder_converted_to_user_message(
        self, mock_llm_config: LLMConfig
    ) -> None:
        """Test that USER_REMINDER is converted to UserMessage (not a different type)."""
        history = [
            ChatMessageSimple(
                message="Test reminder",
                token_count=5,
                message_type=MessageType.USER_REMINDER,
            )
        ]

        raw_result = translate_history_to_llm_format(history, mock_llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 1
        # Should be a UserMessage since LLM APIs don't have a native reminder type
        assert isinstance(result[0], UserMessage)
        assert result[0].role == "user"

    def test_user_reminder_in_mixed_history(self, mock_llm_config: LLMConfig) -> None:
        """Test USER_REMINDER handling when mixed with other message types."""
        history = [
            ChatMessageSimple(
                message="You are a helpful assistant.",
                token_count=10,
                message_type=MessageType.SYSTEM,
            ),
            ChatMessageSimple(
                message="Hello!",
                token_count=5,
                message_type=MessageType.USER,
            ),
            ChatMessageSimple(
                message="Hi there! How can I help?",
                token_count=10,
                message_type=MessageType.ASSISTANT,
            ),
            ChatMessageSimple(
                message="Remember to be concise.",
                token_count=8,
                message_type=MessageType.USER_REMINDER,
            ),
        ]

        raw_result = translate_history_to_llm_format(history, mock_llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 4
        # Check the reminder message (last one)
        reminder_msg = result[3]
        assert isinstance(reminder_msg, UserMessage)
        assert isinstance(reminder_msg.content, str)
        assert reminder_msg.content.startswith(SYSTEM_REMINDER_TAG_OPEN)
        assert reminder_msg.content.endswith(SYSTEM_REMINDER_TAG_CLOSE)
        assert "Remember to be concise." in reminder_msg.content

        # Check that regular USER message is NOT wrapped
        user_msg = result[1]
        assert isinstance(user_msg, UserMessage)
        assert user_msg.content == "Hello!"  # No tags

    def test_regular_user_message_not_wrapped(self, mock_llm_config: LLMConfig) -> None:
        """Test that regular USER messages are NOT wrapped with system-reminder tags."""
        history = [
            ChatMessageSimple(
                message="This is a normal user message.",
                token_count=10,
                message_type=MessageType.USER,
            )
        ]

        raw_result = translate_history_to_llm_format(history, mock_llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg, UserMessage)
        # Regular user message should NOT have the tags
        assert isinstance(msg.content, str)
        assert SYSTEM_REMINDER_TAG_OPEN not in msg.content
        assert SYSTEM_REMINDER_TAG_CLOSE not in msg.content
        assert msg.content == "This is a normal user message."


def _create_llm_config(model_name: str) -> LLMConfig:
    """Create a LLMConfig with the specified model name."""
    return LLMConfig(
        model_provider="openai",
        model_name=model_name,
        temperature=0.7,
        api_key="test-key",
        api_base=None,
        api_version=None,
        max_input_tokens=128000,
    )


class TestCodeBlockMarkdownFormatting:
    """Tests for CODE_BLOCK_MARKDOWN prefix handling in translate_history_to_llm_format.

    OpenAI reasoning models (o1, o3, gpt-5) need a "Formatting re-enabled. " prefix
    in their system messages for correct markdown generation.
    """

    def test_o1_model_prepends_markdown_to_string(self) -> None:
        """Test that o1 model prepends CODE_BLOCK_MARKDOWN to string system message."""
        llm_config = _create_llm_config("o1")
        history = [
            ChatMessageSimple(
                message="You are a helpful assistant.",
                token_count=10,
                message_type=MessageType.SYSTEM,
            )
        ]

        raw_result = translate_history_to_llm_format(history, llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg, SystemMessage)
        assert isinstance(msg.content, str)
        assert msg.content == CODE_BLOCK_MARKDOWN + "You are a helpful assistant."

    def test_o3_model_prepends_markdown(self) -> None:
        """Test that o3 model prepends CODE_BLOCK_MARKDOWN to system message."""
        llm_config = _create_llm_config("o3-mini")
        history = [
            ChatMessageSimple(
                message="System prompt here.",
                token_count=10,
                message_type=MessageType.SYSTEM,
            )
        ]

        raw_result = translate_history_to_llm_format(history, llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg, SystemMessage)
        assert isinstance(msg.content, str)
        assert msg.content.startswith(CODE_BLOCK_MARKDOWN)

    def test_gpt5_model_prepends_markdown(self) -> None:
        """Test that gpt-5 model prepends CODE_BLOCK_MARKDOWN to system message."""
        llm_config = _create_llm_config("gpt-5")
        history = [
            ChatMessageSimple(
                message="System prompt here.",
                token_count=10,
                message_type=MessageType.SYSTEM,
            )
        ]

        raw_result = translate_history_to_llm_format(history, llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg, SystemMessage)
        assert isinstance(msg.content, str)
        assert msg.content.startswith(CODE_BLOCK_MARKDOWN)

    def test_gpt4o_does_not_prepend(self) -> None:
        """Test that gpt-4o model does NOT prepend CODE_BLOCK_MARKDOWN."""
        llm_config = _create_llm_config("gpt-4o")
        history = [
            ChatMessageSimple(
                message="You are a helpful assistant.",
                token_count=10,
                message_type=MessageType.SYSTEM,
            )
        ]

        raw_result = translate_history_to_llm_format(history, llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg, SystemMessage)
        assert isinstance(msg.content, str)
        # Should NOT have the prefix
        assert msg.content == "You are a helpful assistant."
        assert not msg.content.startswith(CODE_BLOCK_MARKDOWN)

    def test_no_system_message_no_crash(self) -> None:
        """Test that history without system message doesn't crash."""
        llm_config = _create_llm_config("o1")
        history = [
            ChatMessageSimple(
                message="Hello!",
                token_count=5,
                message_type=MessageType.USER,
            )
        ]

        raw_result = translate_history_to_llm_format(history, llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg, UserMessage)
        assert msg.content == "Hello!"

    def test_only_first_system_message_modified(self) -> None:
        """Test that only the first system message gets the prefix."""
        llm_config = _create_llm_config("o1")
        history = [
            ChatMessageSimple(
                message="First system prompt.",
                token_count=10,
                message_type=MessageType.SYSTEM,
            ),
            ChatMessageSimple(
                message="Hello!",
                token_count=5,
                message_type=MessageType.USER,
            ),
            ChatMessageSimple(
                message="Second system prompt.",
                token_count=10,
                message_type=MessageType.SYSTEM,
            ),
        ]

        raw_result = translate_history_to_llm_format(history, llm_config)
        result = _ensure_list(raw_result)

        assert len(result) == 3
        # First system message should have prefix
        first_sys = result[0]
        assert isinstance(first_sys, SystemMessage)
        assert isinstance(first_sys.content, str)
        assert first_sys.content.startswith(CODE_BLOCK_MARKDOWN)
        # Second system message should NOT have prefix (only first one is modified)
        second_sys = result[2]
        assert isinstance(second_sys, SystemMessage)
        assert isinstance(second_sys.content, str)
        assert not second_sys.content.startswith(CODE_BLOCK_MARKDOWN)
