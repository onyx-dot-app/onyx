"""Tests for Slack URL parsing and direct thread fetch via URL override."""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.context.search.federated.models import DirectThreadFetch
from onyx.context.search.federated.slack_search import _fetch_thread_from_url
from onyx.context.search.federated.slack_search_utils import extract_slack_message_urls


class TestExtractSlackMessageUrls:
    """Verify URL parsing extracts channel_id and timestamp correctly."""

    def test_standard_url(self) -> None:
        query = "summarize https://mycompany.slack.com/archives/C097NBWMY8Y/p1775491616524769"
        results = extract_slack_message_urls(query)
        assert len(results) == 1
        assert results[0] == ("C097NBWMY8Y", "1775491616.524769")

    def test_multiple_urls(self) -> None:
        query = (
            "compare https://co.slack.com/archives/C111/p1234567890123456 "
            "and https://co.slack.com/archives/C222/p9876543210987654"
        )
        results = extract_slack_message_urls(query)
        assert len(results) == 2
        assert results[0] == ("C111", "1234567890.123456")
        assert results[1] == ("C222", "9876543210.987654")

    def test_no_urls(self) -> None:
        query = "what happened in #general last week?"
        results = extract_slack_message_urls(query)
        assert len(results) == 0

    def test_non_slack_url_ignored(self) -> None:
        query = "check https://google.com/archives/C111/p1234567890123456"
        results = extract_slack_message_urls(query)
        assert len(results) == 0

    def test_timestamp_conversion(self) -> None:
        """p prefix removed, dot inserted after 10th digit."""
        query = "https://x.slack.com/archives/CABC123/p1775491616524769"
        results = extract_slack_message_urls(query)
        channel_id, ts = results[0]
        assert channel_id == "CABC123"
        assert ts == "1775491616.524769"
        assert not ts.startswith("p")
        assert "." in ts


class TestFetchThreadFromUrl:
    """Verify _fetch_thread_from_url calls conversations.replies and returns SlackMessage."""

    @patch("onyx.context.search.federated.slack_search._build_thread_text")
    @patch("onyx.context.search.federated.slack_search.WebClient")
    def test_successful_fetch(
        self, mock_webclient_cls: MagicMock, mock_build_thread: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_webclient_cls.return_value = mock_client

        # Mock conversations_replies
        mock_response = MagicMock()
        mock_response.get.return_value = [
            {"user": "U1", "text": "parent", "ts": "1775491616.524769"},
            {"user": "U2", "text": "reply 1", "ts": "1775491617.000000"},
            {"user": "U3", "text": "reply 2", "ts": "1775491618.000000"},
        ]
        mock_client.conversations_replies.return_value = mock_response

        # Mock channel info
        mock_ch_response = MagicMock()
        mock_ch_response.get.return_value = {"name": "general"}
        mock_client.conversations_info.return_value = mock_ch_response

        mock_build_thread.return_value = (
            "U1: parent\n\nReplies:\n\nU2: reply 1\n\nU3: reply 2"
        )

        fetch = DirectThreadFetch(
            channel_id="C097NBWMY8Y", thread_ts="1775491616.524769"
        )
        result = _fetch_thread_from_url(fetch, "xoxp-token")

        assert len(result.messages) == 1
        msg = result.messages[0]
        assert msg.channel_id == "C097NBWMY8Y"
        assert msg.thread_id is None  # Prevents double-enrichment
        assert msg.slack_score == 100000.0
        assert "parent" in msg.text
        mock_client.conversations_replies.assert_called_once_with(
            channel="C097NBWMY8Y", ts="1775491616.524769"
        )

    @patch("onyx.context.search.federated.slack_search.WebClient")
    def test_api_error_returns_empty(self, mock_webclient_cls: MagicMock) -> None:
        from slack_sdk.errors import SlackApiError

        mock_client = MagicMock()
        mock_webclient_cls.return_value = mock_client
        mock_client.conversations_replies.side_effect = SlackApiError(
            message="channel_not_found",
            response=MagicMock(status_code=404),
        )

        fetch = DirectThreadFetch(channel_id="CBAD", thread_ts="1234567890.123456")
        result = _fetch_thread_from_url(fetch, "xoxp-token")
        assert len(result.messages) == 0
