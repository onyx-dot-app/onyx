"""Unit tests for chat history compression module."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.chat.compression import _build_llm_messages_for_summarization
from onyx.chat.compression import find_summary_for_branch
from onyx.chat.compression import generate_summary
from onyx.chat.compression import get_compression_params
from onyx.chat.compression import get_messages_to_summarize
from onyx.chat.compression import SummaryContent
from onyx.configs.constants import MessageType
from onyx.llm.models import AssistantMessage
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.prompts.compression_prompts import PROGRESSIVE_SUMMARY_SYSTEM_PROMPT_BLOCK
from onyx.prompts.compression_prompts import PROGRESSIVE_USER_REMINDER
from onyx.prompts.compression_prompts import SUMMARIZATION_CUTOFF_MARKER
from onyx.prompts.compression_prompts import SUMMARIZATION_PROMPT
from onyx.prompts.compression_prompts import USER_REMINDER

# Base time for generating sequential timestamps
BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def create_mock_message(
    id: int,
    message: str,
    token_count: int,
    message_type: MessageType = MessageType.USER,
    chat_session_id: int = 1,
    parent_message_id: int | None = None,
    last_summarized_message_id: int | None = None,
    tool_calls: list | None = None,
) -> MagicMock:
    """Create a mock ChatMessage for testing."""
    mock = MagicMock()
    mock.id = id
    mock.message = message
    mock.token_count = token_count
    mock.message_type = message_type
    mock.chat_session_id = chat_session_id
    mock.parent_message_id = parent_message_id
    mock.last_summarized_message_id = last_summarized_message_id
    mock.tool_calls = tool_calls
    # Generate time_sent based on id for chronological ordering
    mock.time_sent = BASE_TIME + timedelta(minutes=id)
    return mock


def test_no_compression_when_under_threshold() -> None:
    """Should not compress when history is under threshold."""
    result = get_compression_params(
        max_input_tokens=10000,
        current_history_tokens=1000,
        reserved_tokens=2000,
    )
    assert result.should_compress is False


def test_compression_triggered_when_over_threshold() -> None:
    """Should compress when history exceeds threshold."""
    result = get_compression_params(
        max_input_tokens=10000,
        current_history_tokens=7000,
        reserved_tokens=2000,
    )
    assert result.should_compress is True
    assert result.tokens_for_recent > 0


def test_get_messages_returns_summary_content() -> None:
    """Should return SummaryContent with correct structure."""
    messages = [
        create_mock_message(1, "msg1", 100),
        create_mock_message(2, "msg2", 100),
    ]
    result = get_messages_to_summarize(
        chat_history=messages,  # type: ignore[arg-type]
        existing_summary=None,
        tokens_for_recent=50,
    )

    assert isinstance(result, SummaryContent)
    assert hasattr(result, "older_messages")
    assert hasattr(result, "recent_messages")


def test_messages_after_summary_cutoff_only() -> None:
    """Should only include messages after existing summary cutoff."""
    messages = [
        create_mock_message(1, "already summarized", 100),
        create_mock_message(2, "also summarized", 100),
        create_mock_message(3, "new message", 100),
    ]
    existing_summary = MagicMock()
    existing_summary.last_summarized_message_id = 2

    result = get_messages_to_summarize(
        chat_history=messages,  # type: ignore[arg-type]
        existing_summary=existing_summary,
        tokens_for_recent=50,
    )

    all_ids = [m.id for m in result.older_messages + result.recent_messages]
    assert 1 not in all_ids
    assert 2 not in all_ids
    assert 3 in all_ids


def test_no_summary_considers_all_messages() -> None:
    """Without existing summary, all messages should be considered."""
    messages = [
        create_mock_message(1, "msg1", 100),
        create_mock_message(2, "msg2", 100),
        create_mock_message(3, "msg3", 100),
    ]

    result = get_messages_to_summarize(
        chat_history=messages,  # type: ignore[arg-type]
        existing_summary=None,
        tokens_for_recent=50,
    )

    all_ids = [m.id for m in result.older_messages + result.recent_messages]
    assert len(all_ids) == 3


def test_empty_messages_filtered_out() -> None:
    """Messages with empty content should be filtered out."""
    messages = [
        create_mock_message(1, "has content", 100),
        create_mock_message(2, "", 0),
        create_mock_message(3, "also has content", 100),
    ]

    result = get_messages_to_summarize(
        chat_history=messages,  # type: ignore[arg-type]
        existing_summary=None,
        tokens_for_recent=50,
    )

    all_messages = result.older_messages + result.recent_messages
    assert len(all_messages) == 2


def test_empty_history_returns_empty() -> None:
    """Should return empty lists for empty history."""
    result = get_messages_to_summarize(
        chat_history=[],
        existing_summary=None,
        tokens_for_recent=100,
    )
    assert result.older_messages == []
    assert result.recent_messages == []


def test_find_summary_for_branch_returns_matching_branch() -> None:
    """Should return summary whose parent_message_id is in current branch."""
    branch_history = [
        create_mock_message(1, "msg1", 100),
        create_mock_message(2, "msg2", 100),
        create_mock_message(3, "msg3", 100),
    ]

    matching_summary = create_mock_message(
        id=100,
        message="Summary of conversation",
        token_count=50,
        parent_message_id=3,
        last_summarized_message_id=2,
    )

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        matching_summary
    ]

    result = find_summary_for_branch(mock_db, branch_history)  # type: ignore[arg-type]

    assert result == matching_summary


def test_find_summary_for_branch_ignores_other_branch() -> None:
    """Should not return summary from a different branch."""
    # Branch B has messages 1, 2, 6, 7 (diverged after message 2)
    branch_b_history = [
        create_mock_message(1, "msg1", 100),
        create_mock_message(2, "msg2", 100),
        create_mock_message(6, "branch b msg1", 100),
        create_mock_message(7, "branch b msg2", 100),
    ]

    # Summary was created on branch A (parent_message_id=5 is NOT in branch B)
    other_branch_summary = create_mock_message(
        id=100,
        message="Summary from branch A",
        token_count=50,
        parent_message_id=5,
        last_summarized_message_id=4,
    )

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        other_branch_summary
    ]

    result = find_summary_for_branch(mock_db, branch_b_history)  # type: ignore[arg-type]

    assert result is None


def test_cutoff_always_before_user_message() -> None:
    """Cutoff should always be placed right before a user message.

    If token budget would place the cutoff between tool calls or assistant messages,
    it should be moved to right before the next user message.
    """
    messages = [
        create_mock_message(1, "user question", 100, MessageType.USER),
        create_mock_message(2, "assistant uses tool", 100, MessageType.ASSISTANT),
        create_mock_message(3, "tool response", 100, MessageType.TOOL_CALL_RESPONSE),
        create_mock_message(4, "assistant continues", 100, MessageType.ASSISTANT),
        create_mock_message(5, "user follow up", 100, MessageType.USER),
        create_mock_message(6, "final answer", 100, MessageType.ASSISTANT),
    ]

    # Token budget that would normally cut between messages 3 and 4
    # (keeping ~300 tokens = messages 4, 5, 6)
    result = get_messages_to_summarize(
        chat_history=messages,  # type: ignore[arg-type]
        existing_summary=None,
        tokens_for_recent=300,
    )

    # recent_messages should start with user message (5), not assistant (4)
    assert result.recent_messages[0].message_type == MessageType.USER
    assert result.recent_messages[0].id == 5

    # Messages 1, 2, 4 should be in older_messages (to be summarized)
    # Note: message 3 (TOOL_CALL_RESPONSE) has content so it's included
    older_ids = [m.id for m in result.older_messages]
    assert 1 in older_ids
    assert 2 in older_ids
    assert 4 in older_ids


def test__build_llm_messages_for_summarization_user_messages() -> None:
    """User messages should be converted to UserMessage objects."""
    messages = [
        create_mock_message(1, "Hello", 10, MessageType.USER),
        create_mock_message(2, "How are you?", 15, MessageType.USER),
    ]

    result = _build_llm_messages_for_summarization(messages, {})  # type: ignore[arg-type]

    assert len(result) == 2
    assert all(isinstance(m, UserMessage) for m in result)
    assert result[0].content == "Hello"
    assert result[1].content == "How are you?"


def test__build_llm_messages_for_summarization_assistant_messages() -> None:
    """Assistant messages should be converted to AssistantMessage objects."""
    messages = [
        create_mock_message(1, "I'm doing great!", 20, MessageType.ASSISTANT),
    ]

    result = _build_llm_messages_for_summarization(messages, {})  # type: ignore[arg-type]

    assert len(result) == 1
    assert isinstance(result[0], AssistantMessage)
    assert result[0].content == "I'm doing great!"


def test__build_llm_messages_for_summarization_tool_calls() -> None:
    """Assistant messages with tool calls should be formatted compactly."""
    mock_tool_call = MagicMock()
    mock_tool_call.tool_id = 1
    msg = create_mock_message(
        1, "Using tool", 20, MessageType.ASSISTANT, tool_calls=[mock_tool_call]
    )

    tool_id_to_name = {1: "search"}

    result = _build_llm_messages_for_summarization([msg], tool_id_to_name)

    assert len(result) == 1
    assert isinstance(result[0], AssistantMessage)
    assert result[0].content == "[Used tools: search]"


def test__build_llm_messages_for_summarization_skips_tool_responses() -> None:
    """Tool response messages should be skipped."""
    messages = [
        create_mock_message(1, "User question", 10, MessageType.USER),
        create_mock_message(
            2, "Tool response data", 50, MessageType.TOOL_CALL_RESPONSE
        ),
        create_mock_message(3, "Assistant answer", 20, MessageType.ASSISTANT),
    ]

    result = _build_llm_messages_for_summarization(messages, {})  # type: ignore[arg-type]

    assert len(result) == 2
    assert isinstance(result[0], UserMessage)
    assert isinstance(result[1], AssistantMessage)


def test__build_llm_messages_for_summarization_skips_empty() -> None:
    """Empty messages should be skipped."""
    messages = [
        create_mock_message(1, "Has content", 10, MessageType.USER),
        create_mock_message(2, "", 0, MessageType.USER),
        create_mock_message(3, "Also has content", 10, MessageType.ASSISTANT),
    ]

    result = _build_llm_messages_for_summarization(messages, {})  # type: ignore[arg-type]

    assert len(result) == 2


def test_generate_summary_initial_system_prompt() -> None:
    """Initial summarization should use SUMMARIZATION_PROMPT as system prompt."""
    older_messages = [
        create_mock_message(1, "User msg", 10, MessageType.USER),
        create_mock_message(2, "Assistant reply", 10, MessageType.ASSISTANT),
    ]
    recent_messages = [
        create_mock_message(3, "Recent user msg", 10, MessageType.USER),
    ]

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.choice.message.content = "Summary of conversation"
    mock_llm.invoke.return_value = mock_response

    with patch("onyx.chat.compression.llm_generation_span"):
        result = generate_summary(
            older_messages=older_messages,  # type: ignore[arg-type]
            recent_messages=recent_messages,  # type: ignore[arg-type]
            llm=mock_llm,
            tool_id_to_name={},
            existing_summary=None,
        )

    assert result == "Summary of conversation"

    # Check the messages passed to the LLM
    call_args = mock_llm.invoke.call_args[0][0]

    # First message should be SystemMessage with just SUMMARIZATION_PROMPT
    assert isinstance(call_args[0], SystemMessage)
    assert call_args[0].content == SUMMARIZATION_PROMPT

    # Should have separate user/assistant messages, not a single concatenated string
    user_messages = [m for m in call_args if isinstance(m, UserMessage)]
    assistant_messages = [m for m in call_args if isinstance(m, AssistantMessage)]

    # Should have: older user msg, cutoff marker, recent user msg, final reminder
    assert len(user_messages) >= 3  # At least: older user, cutoff, reminder
    assert len(assistant_messages) >= 1  # At least: older assistant

    # Final message should be the reminder
    assert isinstance(call_args[-1], UserMessage)
    assert call_args[-1].content == USER_REMINDER


def test_generate_summary_progressive_system_prompt() -> None:
    """Progressive summarization should append PROGRESSIVE_SUMMARY_SYSTEM_PROMPT_BLOCK to system prompt."""
    older_messages = [
        create_mock_message(1, "User msg", 10, MessageType.USER),
    ]
    recent_messages = [
        create_mock_message(2, "Recent msg", 10, MessageType.USER),
    ]
    existing_summary = "Previous conversation summary"

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.choice.message.content = "Updated summary"
    mock_llm.invoke.return_value = mock_response

    with patch("onyx.chat.compression.llm_generation_span"):
        result = generate_summary(
            older_messages=older_messages,  # type: ignore[arg-type]
            recent_messages=recent_messages,  # type: ignore[arg-type]
            llm=mock_llm,
            tool_id_to_name={},
            existing_summary=existing_summary,
        )

    assert result == "Updated summary"

    # Check the messages passed to the LLM
    call_args = mock_llm.invoke.call_args[0][0]

    # First message should be SystemMessage with SUMMARIZATION_PROMPT + PROGRESSIVE_SUMMARY_SYSTEM_PROMPT_BLOCK
    assert isinstance(call_args[0], SystemMessage)
    expected_system = (
        SUMMARIZATION_PROMPT
        + PROGRESSIVE_SUMMARY_SYSTEM_PROMPT_BLOCK.format(
            previous_summary=existing_summary
        )
    )
    assert call_args[0].content == expected_system

    # Final message should be PROGRESSIVE_USER_REMINDER
    assert isinstance(call_args[-1], UserMessage)
    assert call_args[-1].content == PROGRESSIVE_USER_REMINDER


def test_generate_summary_cutoff_marker_as_separate_message() -> None:
    """Cutoff marker should be sent as a separate UserMessage."""
    older_messages = [
        create_mock_message(1, "User msg", 10, MessageType.USER),
    ]
    recent_messages = [
        create_mock_message(2, "Recent msg", 10, MessageType.USER),
    ]

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.choice.message.content = "Summary"
    mock_llm.invoke.return_value = mock_response

    with patch("onyx.chat.compression.llm_generation_span"):
        generate_summary(
            older_messages=older_messages,  # type: ignore[arg-type]
            recent_messages=recent_messages,  # type: ignore[arg-type]
            llm=mock_llm,
            tool_id_to_name={},
            existing_summary=None,
        )

    call_args = mock_llm.invoke.call_args[0][0]

    # Find the cutoff marker message
    cutoff_messages = [
        m
        for m in call_args
        if isinstance(m, UserMessage) and SUMMARIZATION_CUTOFF_MARKER in str(m.content)
    ]
    assert len(cutoff_messages) == 1
    assert cutoff_messages[0].content == SUMMARIZATION_CUTOFF_MARKER


def test_generate_summary_messages_are_separate() -> None:
    """Messages should be sent as separate objects, not concatenated into one string."""
    older_messages = [
        create_mock_message(1, "First user message", 10, MessageType.USER),
        create_mock_message(2, "First assistant reply", 10, MessageType.ASSISTANT),
        create_mock_message(3, "Second user message", 10, MessageType.USER),
    ]
    recent_messages = [
        create_mock_message(4, "Recent message", 10, MessageType.USER),
    ]

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.choice.message.content = "Summary"
    mock_llm.invoke.return_value = mock_response

    with patch("onyx.chat.compression.llm_generation_span"):
        generate_summary(
            older_messages=older_messages,  # type: ignore[arg-type]
            recent_messages=recent_messages,  # type: ignore[arg-type]
            llm=mock_llm,
            tool_id_to_name={},
            existing_summary=None,
        )

    call_args = mock_llm.invoke.call_args[0][0]

    # Should have multiple messages, not just 2 (SystemMessage + single UserMessage)
    assert len(call_args) > 2

    # Count message types
    system_count = sum(1 for m in call_args if isinstance(m, SystemMessage))
    user_count = sum(1 for m in call_args if isinstance(m, UserMessage))
    assistant_count = sum(1 for m in call_args if isinstance(m, AssistantMessage))

    assert system_count == 1  # One system message
    # 3 older user messages + 1 cutoff + 1 recent + 1 reminder = at least 3 user messages
    assert user_count >= 3
    assert assistant_count >= 1  # At least one assistant message from older_messages
