"""A channel the bot cannot join is skipped with a warning, never a failure,
so one archived, restricted, or otherwise unjoinable channel does not stop
the run."""

from typing import Any, cast
from unittest.mock import MagicMock

from slack_sdk.errors import SlackApiError

from onyx.connectors.slack.connector import _get_messages, get_channel_messages
from onyx.connectors.slack.models import ChannelType
from onyx.connectors.slack.source_operations import (
    SlackHistoryPage,
    SlackSourceOperations,
)


def _channel(is_member: bool) -> ChannelType:
    base: dict[str, Any] = {
        "id": "C123",
        "name": "restricted",
        "is_member": is_member,
        "is_private": False,
    }
    return cast(ChannelType, base)


def _client(join_error: str | None) -> MagicMock:
    client = MagicMock(spec=SlackSourceOperations)
    if join_error is not None:
        client.join_channel.side_effect = SlackApiError(
            "slack api error", {"ok": False, "error": join_error}
        )
    client.fetch_channel_history.return_value = iter(
        [SlackHistoryPage(ok=True, messages=[{"ts": "1.0", "text": "hi"}])]
    )
    return client


def test_get_messages_skips_channel_when_join_is_refused() -> None:
    client = _client("restricted_action")

    assert _get_messages(_channel(is_member=False), client) == ([], False)
    client.fetch_channel_history.assert_not_called()


def test_get_channel_messages_yields_nothing_when_join_is_refused() -> None:
    client = _client("restricted_action")

    assert list(get_channel_messages(client, _channel(is_member=False))) == []
    client.fetch_channel_history.assert_not_called()


def test_get_messages_reads_history_after_joining() -> None:
    client = _client(None)

    messages, has_more = _get_messages(_channel(is_member=False), client)

    client.join_channel.assert_called_once_with(channel_id="C123")
    assert [message["text"] for message in messages] == ["hi"]
    assert has_more is False


def test_get_messages_does_not_join_when_already_a_member() -> None:
    client = _client(None)

    _get_messages(_channel(is_member=True), client)

    client.join_channel.assert_not_called()
