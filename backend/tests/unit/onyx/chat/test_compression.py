"""Unit tests for chat history compression module."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock

from onyx.chat.compression import find_summary_for_branch
from onyx.chat.compression import get_compression_params
from onyx.chat.compression import get_messages_to_summarize
from onyx.chat.compression import SummaryContent
from onyx.configs.constants import MessageType

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
