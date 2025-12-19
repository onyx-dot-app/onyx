"""Tests for Slack thread context fetching with rate limit handling."""

from datetime import datetime
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from slack_sdk.errors import SlackApiError

from onyx.context.search.federated.models import SlackMessage
from onyx.context.search.federated.slack_search import _fetch_thread_context
from onyx.context.search.federated.slack_search import (
    fetch_thread_contexts_with_rate_limit_handling,
)
from onyx.context.search.federated.slack_search import SlackRateLimitError
from onyx.context.search.federated.slack_search import ThreadContextResult


def _create_mock_message(
    message_id: str = "1234567890.123456",
    thread_id: str | None = "1234567890.000000",
    text: str = "test message",
    channel_id: str = "C123456",
) -> SlackMessage:
    """Create a mock SlackMessage for testing."""
    return SlackMessage(
        document_id=f"{channel_id}_{message_id}",
        channel_id=channel_id,
        message_id=message_id,
        thread_id=thread_id,
        link=f"https://slack.com/archives/{channel_id}/p{message_id.replace('.', '')}",
        metadata={"channel": "test-channel"},
        timestamp=datetime.now(),
        recency_bias=1.0,
        semantic_identifier="user in #test-channel: test message",
        text=text,
        highlighted_texts=set(),
        slack_score=1000.0,
    )


class TestSlackRateLimitError:
    """Test SlackRateLimitError exception."""

    def test_exception_is_raised(self) -> None:
        """Test that SlackRateLimitError can be raised and caught."""
        with pytest.raises(SlackRateLimitError):
            raise SlackRateLimitError("Rate limited")


class TestThreadContextResult:
    """Test ThreadContextResult class."""

    def test_success_result(self) -> None:
        """Test creating a success result."""
        result = ThreadContextResult.success("enriched text")
        assert result.text == "enriched text"
        assert not result.is_rate_limited
        assert not result.is_error

    def test_rate_limited_result(self) -> None:
        """Test creating a rate limited result."""
        result = ThreadContextResult.rate_limited("original text")
        assert result.text == "original text"
        assert result.is_rate_limited
        assert not result.is_error

    def test_error_result(self) -> None:
        """Test creating an error result."""
        result = ThreadContextResult.error("original text")
        assert result.text == "original text"
        assert not result.is_rate_limited
        assert result.is_error


class TestFetchThreadContext:
    """Test _fetch_thread_context function."""

    def test_non_thread_message_returns_success(self) -> None:
        """Test that non-thread messages return success with original text."""
        message = _create_mock_message(thread_id=None, text="original text")

        result = _fetch_thread_context(message, "xoxp-token", "T12345")

        assert result.text == "original text"
        assert not result.is_rate_limited
        assert not result.is_error

    @patch("onyx.context.search.federated.slack_search.WebClient")
    def test_rate_limit_returns_rate_limited_result(
        self, mock_webclient_class: MagicMock
    ) -> None:
        """Test that 429 rate limit returns rate_limited result."""
        message = _create_mock_message(text="original text")

        # Create mock response with 429 status
        mock_response = MagicMock()
        mock_response.status_code = 429

        # Create mock client that raises rate limit error
        mock_client = MagicMock()
        mock_client.conversations_replies.side_effect = SlackApiError(
            "ratelimited", mock_response
        )
        mock_webclient_class.return_value = mock_client

        result = _fetch_thread_context(message, "xoxp-token", "T12345")

        assert result.text == "original text"
        assert result.is_rate_limited
        assert not result.is_error

    @patch("onyx.context.search.federated.slack_search.WebClient")
    def test_other_api_error_returns_error_result(
        self, mock_webclient_class: MagicMock
    ) -> None:
        """Test that non-rate-limit API errors return error result."""
        message = _create_mock_message(text="original text")

        # Create mock response with non-429 error
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = MagicMock()
        mock_client.conversations_replies.side_effect = SlackApiError(
            "internal_error", mock_response
        )
        mock_webclient_class.return_value = mock_client

        result = _fetch_thread_context(message, "xoxp-token", "T12345")

        assert result.text == "original text"
        assert not result.is_rate_limited
        assert result.is_error

    @patch("onyx.context.search.federated.slack_search.WebClient")
    def test_unexpected_exception_returns_error_result(
        self, mock_webclient_class: MagicMock
    ) -> None:
        """Test that unexpected exceptions return error result."""
        message = _create_mock_message(text="original text")

        mock_client = MagicMock()
        mock_client.conversations_replies.side_effect = RuntimeError("Network error")
        mock_webclient_class.return_value = mock_client

        result = _fetch_thread_context(message, "xoxp-token", "T12345")

        assert result.text == "original text"
        assert not result.is_rate_limited
        assert result.is_error

    @patch("onyx.context.search.federated.slack_search.batch_get_user_profiles")
    @patch("onyx.context.search.federated.slack_search.WebClient")
    def test_successful_thread_fetch_returns_context(
        self, mock_webclient_class: MagicMock, mock_batch_profiles: MagicMock
    ) -> None:
        """Test that successful thread fetch returns enriched context."""
        message = _create_mock_message(
            message_id="1234567890.123456",
            thread_id="1234567890.000000",
            text="original text",
        )

        # Mock user profile lookup
        mock_batch_profiles.return_value = {
            "U111": "User One",
            "U222": "User Two",
            "U333": "User Three",
        }

        # Create mock response with thread messages
        mock_response = MagicMock()
        mock_response.get.return_value = [
            {
                "text": "Thread starter message",
                "user": "U111",
                "ts": "1234567890.000000",
            },
            {"text": "Reply 1", "user": "U222", "ts": "1234567890.111111"},
            {"text": "Reply 2 (matched)", "user": "U333", "ts": "1234567890.123456"},
        ]
        mock_response.validate.return_value = None

        mock_client = MagicMock()
        mock_client.conversations_replies.return_value = mock_response
        mock_webclient_class.return_value = mock_client

        result = _fetch_thread_context(message, "xoxp-token", "T12345")

        # Should contain thread starter and replies with resolved usernames
        assert "Thread starter message" in result.text
        assert "Reply" in result.text
        assert "User One" in result.text
        assert not result.is_rate_limited
        assert not result.is_error


class TestFetchThreadContextsWithRateLimitHandling:
    """Test fetch_thread_contexts_with_rate_limit_handling function."""

    def test_empty_message_list_returns_empty(self) -> None:
        """Test that empty message list returns empty list."""
        result = fetch_thread_contexts_with_rate_limit_handling(
            slack_messages=[],
            access_token="xoxp-token",
            team_id="T12345",
        )

        assert result == []

    @patch("onyx.context.search.federated.slack_search._fetch_thread_context")
    @patch(
        "onyx.context.search.federated.slack_search.run_functions_tuples_in_parallel"
    )
    def test_batch_processing_respects_batch_size(
        self,
        mock_parallel: MagicMock,
        mock_fetch_context: MagicMock,
    ) -> None:
        """Test that messages are processed in batches of specified size."""
        messages = [
            _create_mock_message(message_id=f"123456789{i}.000000") for i in range(7)
        ]

        # Mock parallel execution to return ThreadContextResult objects
        mock_parallel.return_value = [
            ThreadContextResult.success("enriched") for _ in range(3)
        ]

        fetch_thread_contexts_with_rate_limit_handling(
            slack_messages=messages,
            access_token="xoxp-token",
            team_id="T12345",
            batch_size=3,
            max_messages=None,
        )

        # Should have called parallel execution 3 times (7 messages / 3 batch = 3 batches)
        assert mock_parallel.call_count == 3

    @patch("onyx.context.search.federated.slack_search._fetch_thread_context")
    @patch(
        "onyx.context.search.federated.slack_search.run_functions_tuples_in_parallel"
    )
    def test_rate_limit_stops_further_batches(
        self,
        mock_parallel: MagicMock,
        mock_fetch_context: MagicMock,
    ) -> None:
        """Test that rate limiting stops processing of subsequent batches."""
        messages = [
            _create_mock_message(message_id=f"123456789{i}.000000", text=f"msg{i}")
            for i in range(6)
        ]

        # First batch succeeds, second batch has one success and one rate limit
        mock_parallel.side_effect = [
            [
                ThreadContextResult.success("enriched0"),
                ThreadContextResult.success("enriched1"),
            ],
            [
                ThreadContextResult.success("enriched2"),
                ThreadContextResult.rate_limited("msg3"),  # Rate limit hit
            ],
        ]

        result = fetch_thread_contexts_with_rate_limit_handling(
            slack_messages=messages,
            access_token="xoxp-token",
            team_id="T12345",
            batch_size=2,
            max_messages=None,
        )

        # Should have 6 results total
        assert len(result) == 6
        # First 2 should be enriched
        assert result[0] == "enriched0"
        assert result[1] == "enriched1"
        # Second batch: first enriched (preserved!), second rate limited (original text)
        assert result[2] == "enriched2"
        assert result[3] == "msg3"
        # Last 2 (skipped due to rate limit) should be original text
        assert result[4] == "msg4"
        assert result[5] == "msg5"

        # Should only call parallel twice (stopped after rate limit detected)
        assert mock_parallel.call_count == 2

    @patch("onyx.context.search.federated.slack_search._fetch_thread_context")
    @patch(
        "onyx.context.search.federated.slack_search.run_functions_tuples_in_parallel"
    )
    def test_other_errors_dont_stop_processing(
        self,
        mock_parallel: MagicMock,
        mock_fetch_context: MagicMock,
    ) -> None:
        """Test that non-rate-limit errors don't stop batch processing."""
        messages = [
            _create_mock_message(message_id=f"123456789{i}.000000", text=f"msg{i}")
            for i in range(4)
        ]

        # First batch has an error (not rate limit), second batch succeeds
        mock_parallel.side_effect = [
            [
                ThreadContextResult.success("enriched0"),
                ThreadContextResult.error("msg1"),  # Error but NOT rate limit
            ],
            [
                ThreadContextResult.success("enriched2"),
                ThreadContextResult.success("enriched3"),
            ],
        ]

        result = fetch_thread_contexts_with_rate_limit_handling(
            slack_messages=messages,
            access_token="xoxp-token",
            team_id="T12345",
            batch_size=2,
            max_messages=None,
        )

        # Should have 4 results total
        assert len(result) == 4
        assert result[0] == "enriched0"
        assert result[1] == "msg1"  # Error returns original text
        assert result[2] == "enriched2"
        assert result[3] == "enriched3"

        # Should have called both batches (errors don't stop processing)
        assert mock_parallel.call_count == 2


class TestMaxMessagesLimit:
    """Test max_messages parameter limiting thread context fetches."""

    @patch("onyx.context.search.federated.slack_search._fetch_thread_context")
    @patch(
        "onyx.context.search.federated.slack_search.run_functions_tuples_in_parallel"
    )
    def test_max_messages_limits_context_fetches(
        self,
        mock_parallel: MagicMock,
        mock_fetch_context: MagicMock,
    ) -> None:
        """Test that only top N messages get thread context when max_messages is set."""
        messages = [
            _create_mock_message(message_id=f"123456789{i}.000000", text=f"msg{i}")
            for i in range(10)
        ]

        # Mock parallel to return ThreadContextResult for messages that are fetched
        mock_parallel.return_value = [
            ThreadContextResult.success("enriched0"),
            ThreadContextResult.success("enriched1"),
            ThreadContextResult.success("enriched2"),
        ]

        result = fetch_thread_contexts_with_rate_limit_handling(
            slack_messages=messages,
            access_token="xoxp-token",
            team_id="T12345",
            batch_size=5,
            max_messages=3,  # Only fetch context for top 3
        )

        # Should have 10 results total
        assert len(result) == 10
        # First 3 should be enriched
        assert result[0] == "enriched0"
        assert result[1] == "enriched1"
        assert result[2] == "enriched2"
        # Remaining 7 should be original text
        for i in range(3, 10):
            assert result[i] == f"msg{i}"

        # Should only call parallel once (3 messages with batch_size=5 = 1 batch)
        assert mock_parallel.call_count == 1

    @patch("onyx.context.search.federated.slack_search._fetch_thread_context")
    @patch(
        "onyx.context.search.federated.slack_search.run_functions_tuples_in_parallel"
    )
    def test_max_messages_none_fetches_all(
        self,
        mock_parallel: MagicMock,
        mock_fetch_context: MagicMock,
    ) -> None:
        """Test that max_messages=None fetches context for all messages."""
        messages = [
            _create_mock_message(message_id=f"123456789{i}.000000", text=f"msg{i}")
            for i in range(5)
        ]

        mock_parallel.return_value = [
            ThreadContextResult.success(f"enriched{i}") for i in range(5)
        ]

        result = fetch_thread_contexts_with_rate_limit_handling(
            slack_messages=messages,
            access_token="xoxp-token",
            team_id="T12345",
            batch_size=10,
            max_messages=None,  # No limit
        )

        # All 5 should be enriched
        assert len(result) == 5
        for i in range(5):
            assert result[i] == f"enriched{i}"

    @patch("onyx.context.search.federated.slack_search._fetch_thread_context")
    @patch(
        "onyx.context.search.federated.slack_search.run_functions_tuples_in_parallel"
    )
    def test_max_messages_greater_than_total_fetches_all(
        self,
        mock_parallel: MagicMock,
        mock_fetch_context: MagicMock,
    ) -> None:
        """Test that max_messages > total messages fetches all."""
        messages = [
            _create_mock_message(message_id=f"123456789{i}.000000", text=f"msg{i}")
            for i in range(3)
        ]

        mock_parallel.return_value = [
            ThreadContextResult.success("enriched0"),
            ThreadContextResult.success("enriched1"),
            ThreadContextResult.success("enriched2"),
        ]

        result = fetch_thread_contexts_with_rate_limit_handling(
            slack_messages=messages,
            access_token="xoxp-token",
            team_id="T12345",
            batch_size=10,
            max_messages=100,  # More than we have
        )

        # All 3 should be enriched
        assert len(result) == 3
        for i in range(3):
            assert result[i] == f"enriched{i}"
