"""Tests for _build_thread_text function."""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.context.search.federated.slack_search import _build_thread_text


def _make_msg(user: str, text: str, ts: str) -> dict[str, str]:
    return {"user": user, "text": text, "ts": ts}


class TestBuildThreadText:
    """Verify _build_thread_text includes full thread replies up to cap."""

    @patch("onyx.context.search.federated.slack_search.batch_get_user_profiles")
    def test_includes_all_replies(self, mock_profiles: MagicMock) -> None:
        """All replies within cap are included in output."""
        mock_profiles.return_value = {}
        messages = [
            _make_msg("U1", "parent msg", "1000.0"),
            _make_msg("U2", "reply 1", "1001.0"),
            _make_msg("U3", "reply 2", "1002.0"),
            _make_msg("U4", "reply 3", "1003.0"),
        ]
        result = _build_thread_text(messages, "token", "T123", MagicMock())
        assert "parent msg" in result
        assert "reply 1" in result
        assert "reply 2" in result
        assert "reply 3" in result
        assert "..." not in result

    @patch("onyx.context.search.federated.slack_search.batch_get_user_profiles")
    def test_non_thread_returns_parent_only(self, mock_profiles: MagicMock) -> None:
        """Single message (no replies) returns just the parent text."""
        mock_profiles.return_value = {}
        messages = [_make_msg("U1", "just a message", "1000.0")]
        result = _build_thread_text(messages, "token", "T123", MagicMock())
        assert "just a message" in result
        assert "Replies:" not in result

    @patch("onyx.context.search.federated.slack_search.batch_get_user_profiles")
    def test_parent_always_first(self, mock_profiles: MagicMock) -> None:
        """Thread parent message is always the first line of output."""
        mock_profiles.return_value = {}
        messages = [
            _make_msg("U1", "I am the parent", "1000.0"),
            _make_msg("U2", "I am a reply", "1001.0"),
        ]
        result = _build_thread_text(messages, "token", "T123", MagicMock())
        parent_pos = result.index("I am the parent")
        reply_pos = result.index("I am a reply")
        assert parent_pos < reply_pos

    @patch("onyx.context.search.federated.slack_search.batch_get_user_profiles")
    def test_user_profiles_resolved(self, mock_profiles: MagicMock) -> None:
        """User IDs in thread text are replaced with display names."""
        mock_profiles.return_value = {"U1": "Alice", "U2": "Bob"}
        messages = [
            _make_msg("U1", "hello", "1000.0"),
            _make_msg("U2", "world", "1001.0"),
        ]
        result = _build_thread_text(messages, "token", "T123", MagicMock())
        assert "Alice" in result
        assert "Bob" in result
        assert "<@U1>" not in result
        assert "<@U2>" not in result
